# Packaged Food Label Compliance Check Service (Mini Project 10)

Multi-agent service that takes a proposed label + package specification (text, no artwork), validates it, retrieves the
applicable FSSAI provisions from **two regulations**, produces a cited finding per requirement, verifies every citation
against retrieved text, and routes to `clear-for-print` / `revise-and-recheck` / `regulatory-review`.
**It never approves a label.** Category in scope: biscuits / bakery snacks.

> ## READ THIS FIRST - corpus status
> `corpus/raw/*.seed.md` are **paraphrased seed passages** so the stack runs from a clean clone. They are *not* the
> official text; clause numbers and thresholds are placeholders to be verified. Before Evaluation 1, download the two official
> PDFs and swap them in (see `corpus/README.md`). The ingest step warns about any clause id the rule catalogue
> (`app/rules.py`, `app/claims.py`) expects but the index lacks.

## Run it (from a clean clone)
```bash
docker compose up --build          # first run downloads the embedding model (falls back to a hash embedder if offline)
# optional: cp .env.example .env   # only to override; real provider keys go ONLY in .env (git-ignored)
```
| URL | What |
|---|---|
| http://localhost:8000 | web client (submit, poll, citations, escalation path, feedback) |
| http://localhost:8000/docs | OpenAPI; data contract at `/v1/contract` and `contracts/` |
| http://localhost:3000 | Grafana dashboard (no login) |
| http://localhost:16686 | Jaeger traces |
| http://localhost:9090 | Prometheus |

Scale the research agent: `docker compose up --build --scale researcher=3`.
Default LLM is the bundled **stub** (no key). For a real model put `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` (any
OpenAI-compatible free tier) in `.env`; set a spending limit first. Leave `LLM_BASE_URL` empty to run with no model at all
(deterministic path; still grounded and verified).

```bash
curl -s -XPOST localhost:8000/v1/runs -H 'content-type: application/json' -d @scripts/samples/protein_low.json
curl -s localhost:8000/v1/runs/<run_id>            # poll
curl -s localhost:8000/v1/runs/<run_id>/trace      # every tool call, query, passage, prompt version, latency, cost, verification
```

## How it works
```
client -> api (validate + guardrails + quarantine + rate limit + cache) -> Redis q:research
   -> researcher agent (LangGraph, tools, bounded loop) -> EvidenceBundle -> Redis q:assess
   -> assessor agent (LangGraph: draft -> VERIFY -> repair|escalate -> route -> narrate) -> result
```
Details: `docs/ARCHITECTURE.md`. The section 4.1 case: the labelling regulation says only that a claimed nutrient must be
declared; the researcher notices that cue, derives a query from it, finds the claims regulation, follows its reference to
Schedule I, retrieves the NRV, **parses the threshold out of the retrieved text**, and the assessor compares it with the
declared value (4.0 g < 6.0 g = 10% of 60 g NRV) citing both regulations. A single embedding pass (`RETRIEVAL_MODE=single_pass`)
does not find it and the system escalates instead of guessing (see evaluation below).

## Tests, evaluation, load tests
```bash
pip install -r requirements.txt
EMBEDDING_BACKEND=hash INDEX_DIR=/tmp/idx REDIS_URL=fakeredis:// python -m app.rag.ingest && python -m pytest -q
python eval/build_eval_set.py                       # regenerates eval/eval_set.jsonl (26 scenarios)
python eval/run_eval.py --label agentic             # batch eval from the CLI
python eval/run_eval.py --label single_pass --retrieval-mode single_pass
python eval/run_eval.py --compare eval/results/single_pass.json eval/results/agentic.json
python eval/run_eval.py --label p_v2 --prompt-version v2   # prompt A/B (needs a real LLM to differ; see docs/PERFORMANCE.md)
docker compose --profile loadtest up locust          # http://localhost:8089 ; or ./loadtest/run_scaling.sh
python -m app.rag.show_case                          # Evaluation-1: the passages the 4.1 case depends on
```
Measured on the author's dev box (seed corpus, hash embedder, no LLM): see `docs/PERFORMANCE.md` - *these are not your numbers; re-run in Docker*.

## Demo checklist (all ten items)
| # | Item | How |
|---|---|---|
| 1 | clean-clone start | `docker compose up --build`, open http://localhost:8000 |
| 2 | routed recommendation, citations resolve | UI sample "source of protein (7.5 g)"; every citation quote is verbatim in `/trace -> passages_retrieved` |
| 3 | one run traced | `/v1/runs/<id>/trace` + Jaeger (service `researcher`/`assessor`) |
| 4 | malformed rejected + quarantined, no run | UI sample "malformed"; `curl localhost:8000/v1/quarantine`; response has `agent_run_started:false`; `queue_depth` unchanged |
| 5 | out-of-corpus -> escalation | UI sample "dairy" |
| 6 | verification catches unsupported answer | `POST /v1/runs?fault=unsupported` (repaired after exact-clause lookup) and `?fault=persistent` (escalates, no findings); trace shows `verify_findings` failures. Needs `ALLOW_FAULT_INJECTION=true` |
| 7 | prompt injection | UI sample "injection" -> 422 `prompt_injection_suspected`; output filter redacts "approved/certified" in model text |
| 8 | circuit breaker + degradation | `curl -XPOST localhost:9000/admin/mode -H 'content-type: application/json' -d '{"mode":"down"}'`, submit runs (use new `brand_name` each time to avoid the cache); Grafana shows breaker state 2; results carry `degraded:"llm_unavailable"` yet are still verified. Restore: mode `ok` (breaker closes after `CB_RESET_S`) |
| 9 | Locust vs SLO + `--scale` | `docs/SLO.md`, `./loadtest/run_scaling.sh`, fill `docs/PERFORMANCE.md` |
| 10 | section 4.1 | UI sample "source of protein (4.0 g)" -> `revise-and-recheck`, cites ACR Schedule I/Protein, Schedule I/NRV and LDR Reg 5(3) |

## Repo map and ownership
See `docs/TEAM.md` (sp / sg / m split), `docs/ARCHITECTURE.md`, `contracts/DATA_CONTRACT.md`, `docs/RUNBOOK.md`,
`docs/INCIDENT_LOG.md`, `docs/SLO.md`, `docs/PERFORMANCE.md`, `docs/REPORT_TEMPLATE.md`.
