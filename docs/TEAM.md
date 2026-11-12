# Work split: sp, sg, m

Rule: each person owns a vertical slice end-to-end (code, tests, docs, demo item). Interfaces between slices are fixed by `contracts/DATA_CONTRACT.md` (sections 1-3) - change them only with all three agreeing.
Working end-to-end path already exists (week-2 requirement). Everyone runs `python -m pytest -q` before pushing.

## sp - Platform, API and deployment (Units 1-2)
Requirements: F1, F2, F8, A4, A7, A8, D1, D3, D4, D5 (infra side), D7 (rate limit + whole-run cache), D8.
Own: `app/api.py`, `app/contracts.py`, `app/runs.py`, `app/redis_client.py`, `app/logging_setup.py`, `app/obs.py` (tracing/recorder), `Dockerfile`, `docker-compose.yml`, `.env.example`, `ops/` (Prometheus, Grafana, dashboard generator), `web/index.html`, `docs/RUNBOOK.md`, `docs/INCIDENT_LOG.md`, `docs/ARCHITECTURE.md` (boundaries).
To do next: first `docker compose up` from a truly clean clone on Windows/macOS/Linux and fix what breaks; verify Jaeger shows api->researcher->assessor in one trace; verify every Grafana panel has data (cAdvisor limited on Docker Desktop - note it); `--scale researcher=3` Prometheus discovery; log real incidents; reliable-queue upgrade if time.
Demo items: 1, 3 (Jaeger + trace), 4, 8 (infra view), 9 (scale).

## sg - Agents and reasoning (Unit 4)
Requirements: F3, F4, F5, F6, F7, A1, A2, A3, A5, A6 (agent metrics).
Own: `app/agents/*`, `app/claims.py`, `app/rules.py`, `app/category.py`, `app/verifier.py`, `app/router` logic inside assessor, `app/llm.py`, `app/worker.py`, `app/pipeline.py`, `tests/test_pipeline.py`, `tests/test_llm_and_guardrails.py` (breaker tests).
To do next: map `rules.py`/`claims.py` clause ids to the **official** PDFs; extend claims (e.g. protein quality condition if the official text has one); regulation-conflict scenario with two real conflicting passages; tune loop limits; review prompts for the real model; write the "agent design" report section.
Demo items: 2, 5, 6, 8 (breaker behaviour), 10.

## m - Retrieval, LLMOps and evaluation (Unit 3)
Requirements: L1-L6, D2, D6.
Own: `app/rag/*`, `corpus/`, `app/prompts/`, `app/prompts.py`, `app/guardrails.py`, `app/quality.py`, `eval/*`, `loadtest/*`, `llm_stub/*`, `docs/SLO.md`, `docs/PERFORMANCE.md`, `docs/REPORT_TEMPLATE.md` (evaluation + cost sections).
To do next: **download the official PDFs, swap the seed corpus, show the passages at Evaluation 1** (`python -m app.rag.show_case`); rebuild eval expectations; run prompt A/B and cost with a real free-tier model (set a spending limit); commit SLO before any load test; run Locust at 1 and 3 researchers and fill PERFORMANCE.md; cache on/off comparison; optionally add TruLens feedback functions behind `quality.score`.
Demo items: 7, 9 (Locust results), evaluation numbers.

## Timeline suggestion
Week 1: all: clean-clone run + official corpus + clause-id mapping (m,sg), compose/obs fixes (sp). Week 2: eval + prompt A/B (m), robustness + conflicts (sg), dashboard + runbook (sp). Week 3: load tests, report, rehearse the 10-item demo twice; freeze one week before presentation.
