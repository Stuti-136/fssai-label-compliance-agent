# Incident log (genuine development incidents; append yours from the Docker bring-up and demo rehearsal)

## INC-001 - researcher ran claim planning repeatedly; budget stop reason lost
* Detected: live run against the LLM stub showed `researcher llm_calls = 5` for a label with one claim (expected 1).
* Cause: LangGraph passes each node a copy of state; I set scalar flags (`claims_planned`, `stop_reason`, `degraded`) by mutating the input dict, so the update was never persisted. `plan_claims` re-ran on every loop (extra LLM calls, wasted cost) and a budget-exhaustion stop would have been silently ignored.
* Fix: scalar flags moved into one shared mutable `flags` dict created in `init`; added tests `test_llm_called_once_per_claim` and `test_budget_exhaustion_stops_and_escalates`.
* Lesson: in LangGraph, return state updates or share mutable containers; test loop-control flags.

## INC-002 - whole-run cache never populated
* Detected: `test_whole_run_cache_and_idempotency` failed (second identical request not served from cache).
* Cause: an intentionally unconfigured LLM raised `LLMUnavailable`, which the code treated as an outage (`degraded="llm_unavailable"`); degraded results are deliberately excluded from the cache, so nothing was ever cached.
* Fix: only flag degradation when the LLM is configured (`ctx.llm.enabled`); "no model by configuration" is a mode, not a failure.

## INC-003 - TEMPLATE (add the first real failure from `docker compose up` / load test)
* Detected / Cause / Fix / Lesson
