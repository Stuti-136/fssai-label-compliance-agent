"""FastAPI service: ingestion boundary, async run submission, status/trace/feedback, health and metrics.

Why async (A4): a run is several tool calls + model calls (tens of seconds), longer than any sensible HTTP timeout and
variable. POST returns 202 + run_id immediately; the caller polls GET /v1/runs/{id} (polling chosen over callbacks: no
inbound endpoint needed from the analyst's tool, trivially retried, works through proxies). Between submission and
execution sits a Redis queue so the API stays responsive under load and workers scale independently."""
from __future__ import annotations
import json, logging, time, uuid
from pathlib import Path
from fastapi import FastAPI, Header, Request, Response, Body, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from .config import get_settings
from .contracts import validate_request, LabelRequest
from .logging_setup import setup_logging, log, correlation_id
from . import obs, runs, guardrails
from .redis_client import get_redis
from .rag.store import get_index

logger = logging.getLogger("api")
setup_logging("api")
obs.init_tracing("api")
S = get_settings()
app = FastAPI(title="FSSAI Label Compliance Check", version="1.0",
              description="Produces compliance findings with cited evidence. Never approves a label for print.")
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"


@app.middleware("http")
async def mw(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex[:12]
    correlation_id.set(cid)
    t = time.perf_counter()
    route = request.scope.get("route")
    try:
        resp = await call_next(request)
    except Exception:
        logger.exception("unhandled")
        resp = JSONResponse({"error": "internal_error", "correlation_id": cid}, status_code=500)
    path = request.scope.get("route").path if request.scope.get("route") else "unmatched"
    obs.API_REQS.labels(path, request.method, resp.status_code).inc()
    obs.API_LAT.labels(path).observe(time.perf_counter() - t)
    resp.headers["x-correlation-id"] = cid
    if path not in ("/metrics", "/healthz"):
        log(logger, "request", method=request.method, path=request.url.path, status=resp.status_code,
            ms=round((time.perf_counter() - t) * 1000, 1))
    return resp


def _index_meta():
    try:
        m = get_index().meta
        obs.INDEX_CHUNKS.set(m["chunks"])
        obs.INDEX_BUILT_TS.set(m["built_at"])
        obs.INDEX_THROUGHPUT.set(m["throughput_chunks_per_s"])
        return m
    except Exception:
        return None


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    checks, ok = {}, True
    try:
        r = get_redis()
        r.ping()
        checks["redis"] = "ok"
        for q in (runs.Q_RESEARCH, runs.Q_ASSESS):
            obs.QUEUE_DEPTH.labels(q).set(r.llen(q))
    except Exception as e:
        checks["redis"], ok = repr(e), False
    m = _index_meta()
    checks["index"] = f"ok ({m['chunks']} chunks, v{m['index_version']})" if m else "missing"
    ok = ok and bool(m)
    return JSONResponse({"ready": ok, "checks": checks}, status_code=200 if ok else 503)


@app.get("/metrics")
def metrics():
    _index_meta()
    try:
        r = get_redis()
        for q in (runs.Q_RESEARCH, runs.Q_ASSESS):
            obs.QUEUE_DEPTH.labels(q).set(r.llen(q))
    except Exception:
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
def ui():
    return WEB.read_text()


@app.get("/v1/contract")
def contract():
    return LabelRequest.model_json_schema()


@app.get("/v1/index")
def index_info():
    return _index_meta() or JSONResponse({"error": "index not built"}, status_code=503)


@app.post("/v1/runs", status_code=202, summary="Submit a label for a compliance check (async)")
async def submit(request: Request, response: Response, payload=Body(..., description="LabelRequest, see /v1/contract"),
                 fault: str | None = Query(None, description="test only; requires ALLOW_FAULT_INJECTION"),
                 x_client_id: str | None = Header(None), idempotency_key: str | None = Header(None)):
    r = get_redis()
    client = x_client_id or (request.client.host if request.client else "anon")
    ok, retry = runs.check_rate(r, client)
    if not ok:
        obs.RATE_LIMITED.labels("client").inc()
        return JSONResponse({"error": "rate_limited", "retry_after_s": retry}, status_code=429, headers={"Retry-After": str(retry)})
    req, errs = validate_request(payload)
    if errs:  # F2/D1: rejected BEFORE any agent starts; quarantined with field-level errors
        qid = runs.quarantine(r, payload, errs, client)
        log(logger, "request quarantined", logging.WARNING, quarantine_id=qid, errors=errs)
        return JSONResponse({"error": "validation_failed", "quarantined": True, "quarantine_id": qid, "errors": errs,
                             "agent_run_started": False}, status_code=422)
    if fault and not S.allow_fault_injection:
        return JSONResponse({"error": "fault_injection_disabled"}, status_code=400)
    data = req.model_dump(mode="json")
    if idempotency_key:
        prev = r.get(f"idem:{client}:{idempotency_key}")
        if prev:
            return {"run_id": prev, "status_url": f"/v1/runs/{prev}", "idempotent_replay": True}
    cid = correlation_id.get()
    idx_v = (_index_meta() or {}).get("index_version", "none")
    ck = runs.cache_key(data, idx_v)
    cached = None if (fault or not S.cache_enabled) else runs.cache_get(r, ck)
    rid = runs.create_run(r, data, client, cid, fault)
    if idempotency_key:
        r.set(f"idem:{client}:{idempotency_key}", rid, ex=86400)
    if cached:
        cached = {**cached, "run_id": rid, "served_from_cache": True}
        runs.update_run(r, rid, status="completed", result=cached, cache_hit="1")
        obs.RUNS_SUBMITTED.labels("hit").inc()
        return {"run_id": rid, "status_url": f"/v1/runs/{rid}", "cached": True}
    r.lpush(runs.Q_RESEARCH, json.dumps({"run_id": rid, "attempt": 0, "carrier": obs.inject_context()}))
    obs.RUNS_SUBMITTED.labels("miss").inc()
    return {"run_id": rid, "status_url": f"/v1/runs/{rid}", "trace_url": f"/v1/runs/{rid}/trace", "cached": False}


def _watchdog(r, rid, rec):
    if rec["status"] not in runs.TERMINAL and time.time() - float(rec["created_at"]) > S.run_deadline_s:
        runs.fail_run(r, rid, f"deadline {S.run_deadline_s:g}s exceeded", rec["status"])
        return runs.get_run(r, rid)
    return rec


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str):
    r = get_redis()
    rec = runs.get_run(r, run_id)
    if not rec:
        return JSONResponse({"error": "not_found"}, status_code=404)
    rec = _watchdog(r, run_id, rec)
    out = {"run_id": run_id, "status": rec["status"], "created_at": float(rec["created_at"]),
           "updated_at": float(rec["updated_at"]), "correlation_id": rec["correlation_id"]}
    if rec["status"] in runs.TERMINAL:
        out["result"] = json.loads(rec["result"])
    return out


@app.get("/v1/runs/{run_id}/trace")
def trace(run_id: str):
    r = get_redis()
    rec = runs.get_run(r, run_id)
    if not rec:
        return JSONResponse({"error": "not_found"}, status_code=404)
    ev = [json.loads(x) for x in r.lrange(f"trace:{run_id}", 0, -1)]
    ev.sort(key=lambda e: e["ts"])
    steps = [e for e in ev if "latency_ms" in e]
    cost = {}
    for e in ev:
        o = e.get("outputs") or {}
        if e["kind"] == "llm":
            c = cost.setdefault(e["name"], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
            c["calls"] += 1
            c["prompt_tokens"] += o.get("prompt_tokens", 0)
            c["completion_tokens"] += o.get("completion_tokens", 0)
            c["cost_usd"] += o.get("cost_usd", 0)
    b = r.get(f"bundle:{run_id}")
    bundle = json.loads(b) if b else None
    return {"run_id": run_id, "status": rec["status"], "correlation_id": rec["correlation_id"], "request": json.loads(rec["request"]),
            "events": ev, "per_step_latency_ms": [{"agent": e["agent"], "step": f"{e['kind']}:{e['name']}", "ms": e["latency_ms"]} for e in steps],
            "cost_per_step": cost, "total_cost_usd": round(sum(c["cost_usd"] for c in cost.values()), 6),
            "passages_retrieved": [{"chunk_id": k, "clause_id": v["clause_id"], "text": v["text"]} for k, v in (bundle or {}).get("passages", {}).items()],
            "verification": (json.loads(rec["result"]).get("verification") if rec.get("result") else None),
            "prompt_version": S.prompt_version}


@app.post("/v1/runs/{run_id}/feedback")
async def feedback(run_id: str, body: dict = Body(...)):
    r = get_redis()
    if not runs.get_run(r, run_id):
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not isinstance(body.get("satisfactory"), bool) or not isinstance(body.get("reason", ""), str) or len(body.get("reason", "")) > 500:
        return JSONResponse({"error": "invalid", "detail": "satisfactory:bool and reason:str(<=500) required"}, status_code=422)
    reason = body.get("reason", "")
    if guardrails.detect_injection(reason) or guardrails.detect_toxicity(reason):
        obs.GUARD.labels("feedback_rejected").inc()
        return JSONResponse({"error": "rejected_by_guardrail"}, status_code=422)
    res = json.loads(runs.get_run(r, run_id).get("result") or "{}")
    r.rpush("feedback", json.dumps({"ts": time.time(), "run_id": run_id, "satisfactory": body["satisfactory"], "reason": reason,
                                    "route": res.get("route"), "prompt": S.prompt_version}))
    obs.FEEDBACK.labels(str(body["satisfactory"]).lower()).inc()
    return {"stored": True}


@app.get("/v1/feedback/summary")
def feedback_summary():
    rows = [json.loads(x) for x in get_redis().lrange("feedback", 0, -1)]
    by_route: dict = {}
    reasons: dict = {}
    for x in rows:
        b = by_route.setdefault(x["route"] or "unknown", {"n": 0, "satisfactory": 0})
        b["n"] += 1
        b["satisfactory"] += x["satisfactory"]
        if not x["satisfactory"] and x["reason"]:
            reasons[x["reason"][:60]] = reasons.get(x["reason"][:60], 0) + 1
    n = len(rows)
    return {"total": n, "satisfaction_rate": round(sum(x["satisfactory"] for x in rows) / n, 3) if n else None,
            "by_route": by_route, "top_unsatisfactory_reasons": sorted(reasons.items(), key=lambda x: -x[1])[:5]}


@app.get("/v1/quality")
def quality_series():
    return [json.loads(x) for x in get_redis().lrange("quality", -200, -1)]


@app.get("/v1/quarantine")
def quarantine_list(limit: int = 20):
    return [json.loads(x) for x in get_redis().lrange("quarantine", 0, limit - 1)]
