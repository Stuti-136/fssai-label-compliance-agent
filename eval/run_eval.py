"""L3: batch evaluation from the CLI.

  python eval/run_eval.py [--set eval/eval_set.jsonl] [--label NAME] [--out eval/results/NAME.json]
                          [--retrieval-mode agentic|single_pass] [--prompt-version v1|v2]
Reports route accuracy, status accuracy, groundedness, context relevance, faithfulness, hallucination rate
(definitions: app/quality.py). The LLM is whatever LLM_* env configures (unset => deterministic fallback path).
Compare two runs:  python eval/run_eval.py --compare eval/results/a.json eval/results/b.json"""
import argparse, json, os, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ap = argparse.ArgumentParser()
ap.add_argument("--set", default="eval/eval_set.jsonl")
ap.add_argument("--label", default="run")
ap.add_argument("--out")
ap.add_argument("--retrieval-mode")
ap.add_argument("--prompt-version")
ap.add_argument("--compare", nargs=2)
a = ap.parse_args()

if a.compare:
    x, y = (json.load(open(p)) for p in a.compare)
    print(f"{'metric':22}{x['label']:>18}{y['label']:>18}{'delta':>10}")
    for k in x["metrics"]:
        print(f"{k:22}{x['metrics'][k]:>18}{y['metrics'][k]:>18}{round(y['metrics'][k]-x['metrics'][k],4):>10}")
    sys.exit()

os.environ.setdefault("REDIS_URL", "fakeredis://")
if a.retrieval_mode: os.environ["RETRIEVAL_MODE"] = a.retrieval_mode
if a.prompt_version: os.environ["PROMPT_VERSION"] = a.prompt_version
from app.config import get_settings
from app.contracts import validate_request
from app.rag.store import CorpusIndex
from app.redis_client import get_redis
from app.pipeline import run_pipeline
from app import quality

s = get_settings()
idx, r = CorpusIndex(), get_redis()
rows, per = [], []
for line in open(a.set):
    sc = json.loads(line)
    exp = sc["expected"]
    req, errs = validate_request(sc["request"])
    if exp.get("rejected"):
        ok = bool(errs) and (exp["rejected"] == "cross_field" or any(e["code"] == exp["rejected"] for e in errs))
        rows.append({"id": sc["id"], "route_ok": ok, "status_ok": ok, "rejected": True}); continue
    if errs:
        rows.append({"id": sc["id"], "route_ok": False, "status_ok": False, "error": errs}); continue
    t = time.perf_counter()
    res, bundle = run_pipeline(req.model_dump(mode="json"), r, idx)
    got = {f["id"]: f["status"] for f in res["findings"]}
    st_ok = all(got.get(k) == v for k, v in exp["statuses"].items())
    m = quality.score(res, bundle, req.model_dump(mode="json"), {"gold_clauses": exp["gold_clauses"], "statuses": exp["statuses"]})
    per.append(m)
    rows.append({"id": sc["id"], "route": res["route"], "expected_route": exp["route"], "route_ok": res["route"] == exp["route"],
                 "status_ok": st_ok, "steps": res["stats"]["researcher"]["steps"], "tool_calls": res["stats"]["researcher"]["tool_calls"] + res["stats"]["assessor"]["tool_calls"],
                 "cost_usd": res["stats"]["cost_usd"], "seconds": round(time.perf_counter() - t, 3), **m})
    if not rows[-1]["route_ok"] or not st_ok:
        rows[-1]["debug"] = {"got": got, "reason": res["route_reason"][:200]}
n = len(rows)
metrics = {"route_accuracy": round(sum(x["route_ok"] for x in rows) / n, 4),
           "status_accuracy": round(sum(x["status_ok"] for x in rows) / n, 4)}
for k in ("groundedness", "context_relevance", "faithfulness", "hallucination_rate"):
    metrics[k] = round(statistics.mean(p[k] for p in per), 4)
metrics["mean_tool_calls"] = round(statistics.mean(x["tool_calls"] for x in rows if "tool_calls" in x), 2)
out = {"label": a.label, "scenarios": n, "retrieval_mode": s.retrieval_mode, "prompt_version": s.prompt_version,
       "index_version": idx.version, "llm_configured": bool(s.llm_base_url), "metrics": metrics, "rows": rows}
path = Path(a.out or f"eval/results/{a.label}.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=2))
print(json.dumps({k: out[k] for k in ("label", "scenarios", "retrieval_mode", "prompt_version", "metrics")}, indent=2))
for x in rows:
    if not x["route_ok"] or not x["status_ok"]:
        print("MISS", x["id"], x.get("debug") or x.get("error"))
