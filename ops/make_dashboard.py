"""Generates ops/grafana/dashboards/main.json  (python ops/make_dashboard.py)"""
import json
from pathlib import Path
P = []
def panel(title, exprs, unit="short", w=8, h=7):
    x = (len(P) * w) % 24
    y = (len(P) * w // 24) * h
    P.append({"id": len(P) + 1, "type": "timeseries", "title": title, "datasource": {"type": "prometheus", "uid": "prom"},
              "gridPos": {"x": x, "y": y, "w": w, "h": h}, "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
              "targets": [{"expr": e, "legendFormat": l, "refId": chr(65 + i)} for i, (e, l) in enumerate(exprs)]})
q = lambda p, m, by="le": f"histogram_quantile({p}, sum(rate({m}_bucket[1m])) by ({by}))"
panel("Run end-to-end latency p50 / p95 (submission -> result)", [(q(.5, "run_e2e_seconds"), "p50"), (q(.95, "run_e2e_seconds"), "p95")], "s")
panel("Throughput (runs/s): submitted vs completed", [("sum(rate(runs_submitted_total[1m]))", "submitted"), ("sum(rate(run_e2e_seconds_count[1m]))", "completed")], "ops")
panel("Error rate: API 5xx %, agent run errors/s", [('100*sum(rate(api_requests_total{status=~"5.."}[1m]))/clamp_min(sum(rate(api_requests_total[1m])),1e-9)', "API 5xx %"), ('sum(rate(agent_runs_total{outcome="error"}[1m]))', "agent errors/s"), ("sum(rate(rate_limited_total[1m]))", "429/s")])
panel("Availability (up)", [("up", "{{job}} {{instance}}")])
panel("API latency p95 by route", [(q(.95, "api_request_seconds", "le, route"), "{{route}}")], "s")
panel("Queue depth", [("queue_depth", "{{queue}}")])
panel("Agent task success rate", [('sum(rate(agent_runs_total{outcome=~"ok"}[5m])) by (agent)/sum(rate(agent_runs_total[5m])) by (agent)', "{{agent}}")], "percentunit")
panel("Steps per run (avg)", [("sum(rate(agent_run_steps_sum[5m])) by (agent)/sum(rate(agent_run_steps_count[5m])) by (agent)", "{{agent}}")])
panel("Tool calls per run (avg)", [("sum(rate(agent_run_tool_calls_sum[5m])) by (agent)/sum(rate(agent_run_tool_calls_count[5m])) by (agent)", "{{agent}}")])
panel("Agent run latency p95", [(q(.95, "agent_run_seconds", "le, agent"), "{{agent}}")], "s")
panel("Per-step latency p95", [(q(.95, "agent_step_seconds", "le, agent, step"), "{{agent}} {{step}}")], "s", 12)
panel("LLM retry rate & circuit state (2=open)", [("sum(rate(llm_retries_total[1m]))/clamp_min(sum(rate(llm_calls_total[1m])),1e-9)", "retry rate"), ("max(llm_circuit_state)", "breaker state"), ("sum(rate(llm_calls_total[1m])) by (outcome)", "calls {{outcome}}")], "short", 12)
panel("Container uptime (s)", [("time() - process_start_time_seconds", "{{job}} {{instance}}"), ("time() - container_start_time_seconds{name=~\".+\"}", "{{name}}")], "s")
panel("Container CPU (cores)", [('sum(rate(container_cpu_usage_seconds_total{name=~".+"}[1m])) by (name)', "{{name}}")])
panel("Container memory", [('container_memory_working_set_bytes{name=~".+"}', "{{name}}")], "bytes")
panel("LLM cost USD / hour by step (largest driver)", [("sum(increase(llm_cost_usd_total[1h])) by (step)", "{{step}}")], "currencyUSD")
panel("Tokens/s by step", [("sum(rate(llm_tokens_total[1m])) by (step, kind)", "{{step}} {{kind}}")])
panel("Cache hit ratio", [('sum(rate(cache_events_total{result="hit"}[5m])) by (kind)/sum(rate(cache_events_total[5m])) by (kind)', "{{kind}}")], "percentunit")
panel("Live quality score (sampled)", [("quality_score", "{{metric}}")], "percentunit")
panel("Guardrails & rejects", [("sum(rate(guardrail_events_total[5m])) by (type)", "guard {{type}}"), ("sum(rate(runs_rejected_total[5m])) by (reason)", "reject {{reason}}"), ("sum(rate(verification_total[5m])) by (outcome)", "verify {{outcome}}")])
panel("Index freshness: age (s), chunks, build throughput", [("time() - max(index_built_timestamp_seconds)", "index age s"), ("max(index_chunks)", "chunks"), ("max(index_build_chunks_per_second)", "chunks/s at build")])
panel("Feedback", [("sum(increase(feedback_total[1h])) by (satisfactory)", "satisfactory={{satisfactory}}")])
d = {"uid": "fssai-main", "title": "FSSAI label compliance - service", "schemaVersion": 39, "version": 1, "refresh": "5s",
     "time": {"from": "now-30m", "to": "now"}, "panels": P}
Path(__file__).parent.joinpath("grafana/dashboards/main.json").write_text(json.dumps(d, indent=1))
print(len(P), "panels")
