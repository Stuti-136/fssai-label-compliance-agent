# Architecture

```
            +------------------ deployment boundary: each box = container ------------------+
 client --> | api (FastAPI)  validate -> guardrails -> quarantine | rate limit | whole-run cache |
            +----+------------------------------------------------------------------------+---+
                 | LPUSH q:research                                                       | GET status/trace
            +----v-----------+   EvidenceBundle (Redis)   +-----------------+              |
            | researcher xN  | -------------------------> | assessor xM     |              |
            | LangGraph loop |      LPUSH q:assess        | LangGraph       |              |
            | tools: search, |                            | draft->verify-> |              |
            | lookup, field, |                            | repair|escalate |              |
            | xrefs          |                            | ->route->narrate|              |
            +---+--------+---+                            +----+--------+---+              |
                |        | FAISS index (read-only vol)         |        |                  |
                |        +-------------------------------------+        |                  |
                |  OpenAI-compatible calls (timeout/retry/breaker)      |                  |
            +---v------------------------------------------------------v---+          +----v----+
            | llm-stub (default) or real provider                           |          |  redis  |
            +---------------------------------------------------------------+          +---------+
 indexer (one-shot job) -> index_data volume      jaeger / prometheus / grafana / cadvisor observe all
```

## Deployment boundaries (D3) and why
| boundary | reason |
|---|---|
| api | stateless, light, scales on request rate; must stay responsive when agents are saturated (**resource profile, scaling**) |
| researcher | retrieval + many tool calls; the replica to scale (`--scale researcher=3`) (**scaling, resource profile**) |
| assessor | deterministic compute + verification; separate failure domain: it can restart without losing research, bundle persists in Redis (**failure isolation, independent release**) |
| redis | stateful queue/store; persisted volume (**failure isolation**) |
| indexer | corpus pipeline releases independently of the service; writes immutable index generations and atomically switches `active_index.json` (**independent release**) |
| llm-stub | removes provider rate limits from load tests; fault injection for breaker demo (**failure isolation**) |
| jaeger, prometheus, grafana, cadvisor | observability plane, no coupling to run path |

## Agents (A2)
Two agents = two **processes/queues/graphs** with distinct responsibilities and one typed hand-off:
* **Researcher** gathers evidence only. Never decides compliance.
* **Assessor** decides findings from evidence + request, verifies, routes. Has its own tools (exact lookup, lexical search) used only for *repair*.

**Failure mid-run.** Handler error -> retried (`WORKER_MAX_ATTEMPTS`, backoff) -> run `failed` with an incomplete result (`complete:false`, `regulatory-review`, no findings). Researcher process dies -> message retried elsewhere; API watchdog fails the run after `RUN_DEADLINE_S`. Assessor dies -> bundle persists, researcher work not repeated. Known limitation: BRPOP is at-most-once for a message popped by a crashing worker; the watchdog is the backstop (a reliable queue with ack, e.g. BLMOVE + reaper, is the next step).

## Researcher loop (A1) - tools the agent *chooses* via its planner
`search_corpus(query, mode semantic|lexical|hybrid, doc_id, k)`, `lookup_clause(refs)`, `get_request_field(path)`, `extract_cross_references(passages)`.
Bounds: `RUN_MAX_STEPS`, `RUN_MAX_TOOL_CALLS`, `RESEARCH_TIMEOUT_S` (checked before every step; exceeding stops research and the assessor escalates `research_incomplete`).
Section-5 steps: (1) baseline lookup+search; (2) `reflect` scans new passages for modifier cues (claim / exempt / unless / subject to) and cross-references -> new goals; (3) claim goals use a query **derived from what was read** (LLM, heuristic fallback); (4) `reflect` checks the passages really contain the claim condition (parsed by regex), (5) if not: retry with a different strategy hybrid -> lexical -> exact clause lookup, then give up -> unresolved -> escalate.
LLM is used for query derivation and narrative only. **Verdicts are computed**, thresholds parsed from retrieved text.

## Verification (A3)
Per finding: status valid; verdicts have citations; each citation `chunk_id` was retrieved, `clause_id` matches, quote is a verbatim substring; claim numbers (NRV %, limits) appear in the cited text and the declared value equals the request. Fail -> repair (exact lookup of failed clauses / lexical search) -> redraft -> verify; still failing -> findings dropped, route `regulatory-review`. LLM narrative accepted only if it names the route and all clause ids/numbers are grounded; otherwise a template is used. Output filter redacts "approved/certified/compliant" in model text; routes are an enum.

## Resilience (A5)
Timeouts on every LLM call (`LLM_TIMEOUT_S`) and budgets on tools; retries `LLM_MAX_RETRIES` with exponential backoff + jitter; circuit breaker (closed/half-open/open, `CB_*`); fallback path: LLM -> (retry) -> breaker open -> deterministic template/heuristic query (`degraded:"llm_unavailable"`, results still verified) -> if retrieval/index unavailable: run fails -> `regulatory-review`. Incomplete runs never carry findings or confidence.

## Retrieval design (L1) vs the section 3 difficulty
Clause-level chunks with `[doc | clause | title]` header embedded with text; metadata `doc_id`, `clause_id`. Hybrid retrieval = FAISS (LangChain) + BM25 fused with RRF; `doc_id` filter lets the agent target the claims regulation once a cue says "claim"; `lookup_clause` fetches by id/prefix (`ACR-2018:Schedule I` -> all `Schedule I/*`). Embeddings: local sentence-transformers (hash fallback). Re-embedding: vectors cached by (content hash, embedder id); `--reembed`, `--reembed-doc`; unchanged corpus = no-op.

## Observability (D5)
JSON logs with `correlation_id`/`run_id`/`agent`; OTel spans per step exported to Jaeger, trace context carried API -> researcher -> assessor in the queue message; Prometheus scrapes api, every researcher/assessor replica (DNS SD), stub, cAdvisor; Grafana dashboard `ops/grafana/dashboards/main.json`. `GET /v1/runs/{id}/trace` reconstructs a run: tool calls, queries, passages, prompt version, per-step latency, per-step cost, verification.
