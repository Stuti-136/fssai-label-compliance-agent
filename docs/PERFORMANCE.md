# Performance, cost and quality results

Fill the TEMPLATE rows by running the commands. Rows marked DEV-BOX were measured while building (real Redis, API + stub +
1 researcher + 1 assessor as local processes, **not Docker**, hash embedder, seed corpus). Treat as indicative only.

## Load test vs SLO (docs/SLO.md)
| config | users | RPS | p50 | p95 | target met? | notes |
|---|---|---|---|---|---|---|
| DEV-BOX burst, 1+1 processes x4 threads, stub 800ms | 20 concurrent, 60 runs | 3.5 runs/s | 4.99 s | 6.82 s | yes (<10 s @ >=3/s) | not a Locust run |
| TEMPLATE researcher=1 | | | | | | |
| TEMPLATE researcher=3 | | | | | | |
Concurrency at which target fails / responsible component: TEMPLATE (watch `queue_depth{queue="q:research"}` and container CPU).

## Evaluation (26 scenarios, `eval/eval_set.jsonl`; DEV-BOX, hash embedder, no LLM)
The deliberate change = disable agentic follow-up (`RETRIEVAL_MODE=single_pass`: baseline lookup + one semantic search, no cue/reference/claim follow-up).
| metric | single_pass (before) | agentic (after) |
|---|---|---|
| route accuracy | 0.50 | 1.00 |
| status accuracy | 0.50 | 1.00 |
| groundedness | 1.00 | 1.00 |
| context relevance | 0.91 | 0.72 |
| faithfulness | 1.00 | 1.00 |
| hallucination rate | 0.00 | 0.00 |
| mean tool calls | 2.9 | 8.1 |
Reading: every claim scenario fails in single-pass **by escalating, not by fabricating** (hallucination stays 0) - the verification/escalation design working. Agentic recovers them at the price of ~5 more tool calls and lower context relevance (it also pulls neighbouring Schedule I clauses). Caveat: the eval set was authored together with the rule catalogue, so 1.00 on the seed corpus is partly by construction; rebuild expectations after switching to the official PDFs. Metric definitions: `app/quality.py`.

## Prompt variants (L2) - TEMPLATE
Run `eval/run_eval.py --label p_v1 --prompt-version v1` and `--label p_v2 --prompt-version v2` **with a real LLM configured**, then `--compare`. With no LLM or the stub the prompts are never effective (verdicts are computed), so results are identical - do not report a difference you did not measure. Suggested metric: rate of accepted derived queries (trace `llm:derive_query.accepted`) and faithfulness/groundedness of accepted narratives (`summary_source=="llm"`).

## Cost per 100 runs (L5) - TEMPLATE
With a real provider: read `total_cost_usd` from traces or Grafana "LLM cost by step". Cost per 100 runs = 100 x mean `stats.cost_usd`. Largest driver: compare `cost_per_step` (`derive_query` runs once per nutrient claim in the researcher, `justify` once per run in the assessor); expected driver = `derive_query` on claim-heavy labels. Stub: $0.

## Cache effect (D7) - TEMPLATE
Run Locust twice: `LOCUST_CACHE_BUST=1` (all misses) vs `0` (whole-run cache hits). Report p95 and cost/run for each. Retrieval cache (`rc:` keys) and query-embedding LRU are visible in `cache_events_total{kind=...}`.
