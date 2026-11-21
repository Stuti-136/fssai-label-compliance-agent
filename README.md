# FSSAI Food Label Compliance Checker

A decision-support demo for structured food-label data. FastAPI validates submissions and queues runs; a researcher
retrieves regulatory passages and an assessor generates and verifies cited findings. A Streamlit UI submits assessments
and displays results, citations, and trace evidence.

**This is not FSSAI certification, legal advice, or approval to print.** A qualified regulatory professional must verify
the current applicable rules and make the final decision.

## Features

- Structured request validation, injection guardrails, rate limiting, idempotency, and asynchronous run polling.
- Clause-aware Markdown/PDF parsing, local embeddings, FAISS semantic retrieval, BM25 lexical retrieval, and RRF hybrid search.
- Researcher/assessor workers, citation verification, escalation when evidence is missing, Redis-backed trace, and LLM fallback.
- FastAPI docs and JSON Schema contract, browser client, Streamlit frontend, Prometheus metrics, and optional tracing.
- Tests and evaluation scenarios for routing, claims, guardrails, PDF ingestion, atomic index publication, and UI/API client behavior.

The category selector accepts common packaged-food categories. The existing automated category workflow remains
configured only for **biscuits and bakery snacks**; other categories are accepted as input but escalated for human review.
Selecting a category does not establish regulatory coverage, and category-specific provisions are not inferred.

## Architecture and technology

```text
Streamlit -> FastAPI -> Redis q:research -> Researcher -> EvidenceBundle in Redis
                                            -> Redis q:assess -> Assessor -> result/trace
                         FAISS + BM25 corpus index                     |
                         OpenAI-compatible LLM or deterministic fallback
```

Core stack: Python 3.11+, FastAPI, Pydantic, Redis, LangGraph, LangChain FAISS, NumPy, PyPDF, Streamlit, and pytest.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for deployment boundaries, agent flow, and operational details.

## Repository layout

```text
app/                 API, request contract, rules, agents, workers, RAG, observability
contracts/           Request schema and data contract
corpus/raw/           Seed Markdown documents (paraphrases, not official regulations)
corpus/source_pdfs/   Supplied regulatory source PDFs
docs/                 Architecture, runbook, SLO, performance, and project notes
eval/                 Evaluation data and runner
llm_stub/             OpenAI-compatible development stub
scripts/samples/      JSON demonstration requests
streamlit_app.py      Streamlit frontend
tests/                Automated tests
web/                  Existing FastAPI-served browser client
```

## Windows quick start (Docker Desktop)

From PowerShell in the repository root:

```powershell
Copy-Item .env.example .env
# Optional fast/offline demo: set EMBEDDING_BACKEND=hash in .env.
docker compose up --build
```

Open:

| URL | Service |
|---|---|
| <http://localhost:8501> | Streamlit user interface |
| <http://localhost:8000> | Existing browser client |
| <http://localhost:8000/docs> | FastAPI / OpenAPI documentation |
| <http://localhost:8000/v1/contract> | Live request JSON Schema |
| <http://localhost:3000> | Grafana |
| <http://localhost:16686> | Jaeger |
| <http://localhost:9090> | Prometheus |

Stop with `Ctrl+C`, or in another PowerShell window run `docker compose down`. Docker volumes holding Redis and the
generated index are not removed by that command. Do not remove volumes if you need to preserve local run/index data.

Scale the researcher workers with:

```powershell
docker compose up --build --scale researcher=3
```

The compose file configures Streamlit to call `http://api:8000` inside Docker. To use another deployment, set
`FSSAI_API_BASE_URL` to an API URL reachable from the frontend container/process.

## Windows local development

Create and activate a virtual environment, then install dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The full asynchronous application needs Redis. The simplest local backend is Docker Redis and the bundled LLM stub:

```powershell
docker compose up -d redis llm-stub
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:LLM_BASE_URL = "http://127.0.0.1:9000/v1"
$env:LLM_MODEL = "stub-model"
$env:EMBEDDING_BACKEND = "hash"
$env:CORPUS_DIR = "corpus\raw"
$env:INDEX_DIR = "data\index"
python -m app.rag.ingest
```

In separate PowerShell terminals, set the same environment variables and launch:

```powershell
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

```powershell
$env:WORKER_ROLE = "researcher"; $env:METRICS_PORT = "8002"
python -m app.worker
```

```powershell
$env:WORKER_ROLE = "assessor"; $env:METRICS_PORT = "8003"
python -m app.worker
```

```powershell
$env:FSSAI_API_BASE_URL = "http://127.0.0.1:8000"
streamlit run streamlit_app.py
```

`$env:` values are per PowerShell process. The `.env` file is read by Docker Compose, not by a bare Python process.
For a complete local stack, Docker Compose is the recommended path.

## Regulatory corpus and ingestion

`corpus/raw/*.seed.md` contains paraphrased demonstration text. It is not official regulatory content and must not be used
to make a real compliance decision. Four source PDFs are preserved under `corpus/source_pdfs/`, including two labelling
editions and an advertising/claims compendium plus a Gazette notification. Do not index multiple editions of one canonical
document together: ingestion now rejects duplicate canonical IDs to avoid silently combining versions.

For a controlled local build, stage one intended edition of each source without modifying or deleting the originals:

```powershell
New-Item -ItemType Directory -Force corpus\active | Out-Null
Copy-Item "corpus\source_pdfs\Comp_Labelling Display_Version VIII_09_09_2025.pdf" "corpus\active\LDR-2020.pdf"
Copy-Item "corpus\source_pdfs\Compendium_Advertising_Claims_Regulations_04_10_2022.pdf" "corpus\active\ACR-2018.pdf"
python -m app.rag.ingest --corpus corpus\active --out data\official-index
```

This command verifies extraction and builds an index; it does **not** by itself certify that every rule reference is current
or that an amendment is incorporated. Review the extracted passages and confirm the applicable current official sources
before using the rules. Do not replace clauses or thresholds based only on evaluation labels.

For Docker, stage the intended corpus on the host first, then set `CORPUS_DIR` and `INDEX_DIR` in `.env` to paths visible
inside the container (for example, `/app/corpus/active` and `/data/official-index`). Build the image after staging the
corpus so the indexer image contains those files, run the one-shot indexer, then start the services:

```powershell
docker compose build
docker compose run --rm indexer
docker compose up
```

## Environment configuration

Copy `.env.example` to `.env` for Compose overrides. Common settings:

- `FSSAI_API_BASE_URL`: FastAPI address reachable from the UI.
- `REDIS_URL`: Redis connection.
- `CORPUS_DIR`, `INDEX_DIR`: ingestion input and active index root.
- `EMBEDDING_BACKEND=st|hash`, `EMBEDDING_MODEL`: local embeddings. `hash` avoids downloading a model but has lower retrieval quality.
- `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`: optional OpenAI-compatible provider. Leave the base URL empty for deterministic fallback.
- `RETRIEVAL_MODE`, `PROMPT_VERSION`: retrieval and prompt variants.
- `ALLOW_FAULT_INJECTION`: demo/test-only. Set `false` outside a controlled demo.

Never commit provider keys or `.env`.

## Using the Streamlit app

The UI has Home, New assessment, Results, Evidence & sources, and About sections. It includes three demonstration inputs:

1. A label that appears clear based on the supplied data.
2. A low-protein “Source of Protein” claim that illustrates an identifiable issue against the configured corpus.
3. An immunity claim that should be escalated for human review.

The category selector includes biscuits/bakery, beverages/juices, dairy, snacks/savoury, confectionery/chocolates,
cereals/breakfast, instant/ready-to-eat foods, spices/seasonings, sauces/dips/condiments, edible oils/fats,
pulses/packaged grains, nutritional/health foods, and Other with a custom description. These are demo scenarios,
not legal determinations. The request contract currently does not accept artwork uploads, OCR,
actual manufacture/expiry dates, or storage instructions. The UI does not claim to process those fields. Evidence pages
show passage text, clause, document title/version, and chunk ID; source page numbers are unavailable in the current parser.

The Streamlit API client submits to `POST /v1/runs`, polls `GET /v1/runs/{id}`, and fetches `GET /v1/runs/{id}/trace`.
HTTP validation errors and unavailable backends are displayed rather than replaced with a success-shaped result.

## Tests and evaluation

```powershell
python -m pytest -q
python eval\build_eval_set.py
python eval\run_eval.py --label agentic
python eval\run_eval.py --label single_pass --retrieval-mode single_pass
python eval\run_eval.py --compare eval\results\single_pass.json eval\results\agentic.json
```

The tests use seed Markdown for deterministic end-to-end scenarios and the included PDFs for parser/ingestion checks.
The evaluation clause IDs have been checked against the supplied LDR Version VIII and ACR 2022 PDFs, but scenario
outcomes and thresholds are demo data based on the paraphrased seed corpus; retrieval metrics therefore depend on which
corpus is indexed and are not legal validation. In particular, ACR protein conditions are expressed as a percentage of
RDA, and this project does not verify the applicable RDA value. Protein claims against that official text are escalated
for human review when the condition cannot be established. Do not use seed thresholds for compliance decisions.

## Known limitations and disclaimer

- Rules and claim detection cover a limited, structured text contract and a narrow food-category scope.
- Some rules are deterministic heuristics; the system cannot inspect artwork, verify ingredient order, validate all exemptions,
  or assess every label requirement.
- Source PDF parsing is text-layer-based, has no OCR or page-number mapping, and must be checked for extraction quality.
- Multiple document versions should be curated before ingestion; amendments and consolidated editions need regulatory review.
- The seed corpus is paraphrased demonstration data. A “clear-for-print” route is only a recommendation based on supplied
  inputs/evidence and never grants approval to print.

This software is an assistance tool, not official FSSAI certification or legal advice. Human review is required for final
regulatory decisions.
