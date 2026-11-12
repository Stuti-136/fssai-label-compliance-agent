"""Agent worker. One image, two roles (WORKER_ROLE=researcher|assessor), each its own compose service, queue and
process => two real agents with a defined hand-off (the EvidenceBundle in Redis).

Failure semantics:
  * message handling error -> retried up to WORKER_MAX_ATTEMPTS with backoff, then run is marked FAILED
    (incomplete result, route regulatory-review, no confident answer).
  * researcher dies mid-run -> run stays 'researching'; message is retried by another replica; API watchdog fails the run
    after RUN_DEADLINE_S.
  * assessor dies -> the bundle is kept in Redis; message retried; the researcher's work is not repeated.
"""
from __future__ import annotations
import json, logging, os, random, signal, socket, threading, time
from prometheus_client import start_http_server
from .config import get_settings
from .logging_setup import setup_logging, log, correlation_id, run_id_var, agent_var
from . import obs, runs, pipeline, quality
from .redis_client import get_redis
from .rag.store import get_index

logger = logging.getLogger("worker")
STOP = threading.Event()
ROLE = os.environ.get("WORKER_ROLE", "researcher")


def heartbeat(r):
    while not STOP.is_set():
        try:
            r.set(f"hb:{ROLE}:{socket.gethostname()}", time.time(), ex=60)
        except Exception:
            pass
        STOP.wait(10)


def handle_research(r, msg):
    rid = msg["run_id"]
    rec = runs.get_run(r, rid)
    req = json.loads(rec["request"])
    runs.update_run(r, rid, status="researching")
    idx = get_index()
    bundle = pipeline.research(rid, req, r, idx)
    r.set(f"bundle:{rid}", json.dumps(bundle), ex=7 * 86400)
    runs.update_run(r, rid, status="assessing", index_version=idx.version)
    r.rpush("trace:" + rid, json.dumps({"ts": time.time(), "run_id": rid, "agent": "researcher", "kind": "handoff",
                                        "name": "bundle_to_assessor", "outputs": {"passages": len(bundle["passages"]), "unresolved": bundle["unresolved"]}}))
    r.lpush(runs.Q_ASSESS, json.dumps({**msg, "attempt": 0, "carrier": obs.inject_context()}))


def handle_assess(r, msg):
    rid = msg["run_id"]
    rec = runs.get_run(r, rid)
    req = json.loads(rec["request"])
    bundle = json.loads(r.get(f"bundle:{rid}"))
    idx = get_index()
    fault = rec.get("fault") or None
    res = pipeline.assess(rid, req, bundle, r, idx, fault=fault)
    created = float(rec["created_at"])
    res["stats"]["e2e_seconds"] = round(time.time() - created, 3)
    runs.finalize_run(r, rid, res)
    obs.RUN_E2E.labels(res["route"]).observe(res["stats"]["e2e_seconds"])
    if res["verification"]["ok"] and not res["degraded"] and not fault and res["complete"]:
        runs.cache_put(r, runs.cache_key(req, idx.version), res)
    if random.random() < get_settings().quality_sample_rate and not fault:  # L6 live sampling
        try:
            sc = quality.score(res, bundle, req)
            for k, v in sc.items():
                obs.QUALITY.labels(k).set(v)
            r.rpush("quality", json.dumps({"ts": time.time(), "run_id": rid, **sc}))
            r.ltrim("quality", -2000, -1)
        except Exception:
            logger.warning("quality sampling failed", exc_info=True)


def loop(r, queue, handler, stage):
    s = get_settings()
    while not STOP.is_set():
        try:
            item = r.brpop(queue, timeout=2)
        except Exception:
            logger.warning("redis unavailable", exc_info=True)
            STOP.wait(2)
            continue
        if not item:
            continue
        msg = json.loads(item[1])
        rid = msg["run_id"]
        rec = runs.get_run(r, rid) or {}
        if rec.get("status") in runs.TERMINAL:
            continue
        run_id_var.set(rid)
        correlation_id.set(rec.get("correlation_id", rid))
        agent_var.set(stage)
        try:
            with obs.tracer().start_as_current_span(f"{stage}.handle", context=obs.extract_context(msg.get("carrier"))):
                handler(r, msg)
            log(logger, "stage complete", stage=stage)
        except Exception as e:
            att = msg.get("attempt", 0) + 1
            log(logger, "stage failed", logging.ERROR, stage=stage, attempt=att, error=repr(e))
            if att < s.max_attempts:
                time.sleep(0.5 * 2 ** att)
                msg["attempt"] = att
                r.lpush(queue, json.dumps(msg))
            else:
                runs.fail_run(r, rid, repr(e)[:200], stage)


def main():
    s = get_settings()
    setup_logging(ROLE)
    obs.init_tracing(ROLE)
    start_http_server(s.metrics_port)
    r = get_redis()
    get_index()
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    q, h = (runs.Q_RESEARCH, handle_research) if ROLE == "researcher" else (runs.Q_ASSESS, handle_assess)
    ts = [threading.Thread(target=loop, args=(r, q, h, ROLE), daemon=True) for _ in range(s.worker_concurrency)]
    ts.append(threading.Thread(target=heartbeat, args=(r,), daemon=True))
    for t in ts:
        t.start()
    log(logger, "worker started", role=ROLE, concurrency=s.worker_concurrency)
    STOP.wait()
    for t in ts:
        t.join(timeout=5)


if __name__ == "__main__":
    main()
