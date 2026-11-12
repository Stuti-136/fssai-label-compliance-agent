# Service level objective (D6) - declared before measuring

Declared: 2026-11-11 (commit this file **before** any Locust run; do not edit targets after seeing results - add a dated
amendment section instead).

**Context (section 1).** The service sits in front of a manual regulatory-affairs check that takes hours and precedes a
print run. It is not interactive; the analyst submits and does other work. A result inside a minute is already a large
improvement; what matters is that it is predictable and that load does not make it unbounded.

| scope | SLO |
|---|---|
| Production-like (real LLM, one analyst team) | **p95 end-to-end <= 60 s**, availability of submit endpoint >= 99% |
| Load test (LLM stub, delay 800 ms +-300 ms, cache-busting ON) | **p95 end-to-end <= 10 s at >= 3 completed runs/s sustained for 3 min with `researcher=1`**; run failure rate < 1% |
Measured **from submission to final result** (Locust task = POST + poll until `completed`, event "end-to-end run").

Justification: a run is ~2 stub LLM calls (~1.6 s) plus local retrieval; 10 s allows ~6x queueing headroom, 60 s for a real provider covers ~6 sequential calls at free-tier latency with retries.

To report (docs/PERFORMANCE.md): RPS, p50, p95 vs target and met/not met; the concurrency (users) at which p95 first exceeds the target and the component responsible (queue depth, researcher CPU, Redis, stub); effect of `--scale researcher=3`; if scaling does not help, the real bottleneck.
