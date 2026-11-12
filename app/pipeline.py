"""Shared run logic used by the workers (queue-driven) and by eval / tests (in-process)."""
from __future__ import annotations
import time, uuid
from types import SimpleNamespace
from .config import get_settings
from .llm import get_llm
from .obs import TraceRecorder
from .agents.tools import Budget
from .agents.researcher import run_research
from .agents.assessor import run_assess


def research(run_id, request, redis, index, llm=None):
    s = get_settings()
    rec = TraceRecorder(redis, run_id, "researcher", s.prompt_version)
    ctx = SimpleNamespace(run_id=run_id, request=request, redis=redis, index=index, llm=llm or get_llm(), rec=rec,
                          settings=s, budget=Budget(s.run_max_steps, s.run_max_tool_calls, s.research_timeout_s))
    try:
        b = run_research(ctx)
        rec.finish("ok" if not b["stop_reason"] or b["stop_reason"].startswith("category") else "budget")
        return b
    except Exception:
        rec.finish("error")
        raise


def assess(run_id, request, bundle, redis, index, llm=None, fault=None):
    s = get_settings()
    rec = TraceRecorder(redis, run_id, "assessor", s.prompt_version)
    ctx = SimpleNamespace(run_id=run_id, request=request, bundle=bundle, redis=redis, index=index, llm=llm or get_llm(),
                          rec=rec, settings=s, fault=fault or None,
                          budget=Budget(s.run_max_steps, s.run_max_tool_calls, s.assess_timeout_s))
    try:
        res = run_assess(ctx)
        rec.finish("ok" if res["verification"]["ok"] else "unverified")
    except Exception:
        rec.finish("error")
        raise
    res["versions"] = {"prompt": s.prompt_version, "index": index.version, "corpus": {k: v["version"] for k, v in index.meta["documents"].items()},
                       "retrieval_mode": s.retrieval_mode}
    res["stats"] = {"researcher": bundle["stats"], "assessor": rec.stats()}
    res["stats"]["cost_usd"] = round(bundle["stats"]["cost_usd"] + rec.cost, 6)
    res["stats"]["prompt_tokens"] = bundle["stats"]["prompt_tokens"] + rec.ptok
    res["stats"]["completion_tokens"] = bundle["stats"]["completion_tokens"] + rec.ctok
    return res


def run_pipeline(request: dict, redis, index, llm=None, fault=None, run_id=None):
    """Synchronous researcher -> assessor (no queue). Returns (result, bundle)."""
    rid = run_id or uuid.uuid4().hex[:16]
    t = time.perf_counter()
    b = research(rid, request, redis, index, llm)
    res = assess(rid, request, b, redis, index, llm, fault)
    res["stats"]["e2e_seconds"] = round(time.perf_counter() - t, 3)
    return res, b
