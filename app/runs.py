"""Run store, quarantine, cache, rate limit — all Redis-backed (D1, D7)."""
from __future__ import annotations
import hashlib, json, time, uuid
from .config import get_settings
from . import obs

TERMINAL = {"completed", "failed"}
Q_RESEARCH, Q_ASSESS = "q:research", "q:assess"
DISCLAIMER = ("Compliance finding only. This system never approves a label for print; "
              "a regulatory affairs professional makes the decision.")


def canon_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_run(r, request: dict, client_id: str, correlation_id: str, fault: str | None = None) -> str:
    rid = uuid.uuid4().hex[:16]
    now = time.time()
    r.hset(f"run:{rid}", mapping={"status": "queued", "created_at": now, "updated_at": now, "client_id": client_id,
                                   "correlation_id": correlation_id, "request": json.dumps(request),
                                   "fault": fault or "", "cache_hit": "0"})
    r.expire(f"run:{rid}", 7 * 86400)
    return rid


def get_run(r, rid: str) -> dict | None:
    d = r.hgetall(f"run:{rid}")
    return d or None


def update_run(r, rid: str, **kw):
    kw["updated_at"] = time.time()
    r.hset(f"run:{rid}", mapping={k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in kw.items()})


def incomplete_result(rid: str, why: str, stage: str) -> dict:
    return {"run_id": rid, "status": "failed", "complete": False, "route": "regulatory-review",
            "route_reason": f"Run did not complete ({stage}: {why}). No determination was made; send to a human reviewer.",
            "findings": [], "escalations": [{"trigger": "run_incomplete", "detail": why}], "summary": None,
            "verification": {"ok": False, "attempts": 0, "failures": []}, "disclaimer": DISCLAIMER}


def fail_run(r, rid: str, why: str, stage: str):
    res = incomplete_result(rid, why, stage)
    update_run(r, rid, status="failed", error=f"{stage}: {why}", result=res)
    obs.RUN_E2E.labels("failed").observe(max(0, time.time() - float((get_run(r, rid) or {}).get("created_at", time.time()))))


def finalize_run(r, rid: str, result: dict):
    update_run(r, rid, status="completed", result=result)


# ---- quarantine (F2/D1)
def quarantine(r, payload, errors: list[dict], client_id: str) -> str:
    qid = uuid.uuid4().hex[:12]
    raw = json.dumps(payload, default=str)[:8000]
    r.lpush("quarantine", json.dumps({"id": qid, "ts": time.time(), "client_id": client_id, "errors": errors,
                                      "payload_truncated": raw}))
    r.ltrim("quarantine", 0, 999)
    for e in errors:
        obs.RUNS_REJECTED.labels(e["code"]).inc()
        if e["code"] in ("prompt_injection_suspected", "toxic_content"):
            obs.GUARD.labels(e["code"]).inc()
    return qid


# ---- rate limit (D7): fixed window per client; protects the model budget
def check_rate(r, client_id: str) -> tuple[bool, int]:
    lim = get_settings().rate_limit_per_min
    w = int(time.time() // 60)
    k = f"rl:{client_id}:{w}"
    n = r.incr(k)
    if n == 1:
        r.expire(k, 90)
    return n <= lim, 60 - int(time.time() % 60)


# ---- whole-run cache (D7)
def cache_key(request: dict, index_version: str) -> str:
    s = get_settings()
    return f"runcache:{canon_hash(request)}:{index_version}:{s.prompt_version}:{s.retrieval_mode}"


def cache_get(r, key: str):
    v = r.get(key)
    obs.CACHE.labels("run", "hit" if v else "miss").inc()
    return json.loads(v) if v else None


def cache_put(r, key: str, result: dict):
    r.set(key, json.dumps(result), ex=get_settings().cache_ttl_s)
