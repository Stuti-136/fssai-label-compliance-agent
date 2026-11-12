# Report outline (plain, brief)
1. Problem and scope (category: biscuits/bakery; two regulations; never approves)
2. Agent design: topology (researcher/assessor), tools, verification, loop limits (see ARCHITECTURE.md)
3. Architecture diagram with deployment boundaries (ARCHITECTURE.md)
4. Design decisions and rejected alternatives - e.g. rejected: single embedding pass (fails 4.1), LLM-decided verdicts (unverifiable), in-process second "agent" (not independent), Celery (extra dependency vs a Redis list), push callbacks (needs inbound endpoint)
5. Evaluation before/after (PERFORMANCE.md) and prompt A/B
6. p95 target, measured results, bottleneck, cost per 100 runs
7. What did not work (INCIDENT_LOG.md + honest limitations: seed vs official corpus, at-most-once queue, regex-parsed conditions, keyword claim detection, hash embedder fallback)
