"""Metrics (Prometheus), tracing (OpenTelemetry) and the per-run TraceRecorder (D5, A6, L5)."""
from __future__ import annotations
import json, time, logging
from contextlib import contextmanager
from prometheus_client import Counter, Histogram, Gauge
from opentelemetry import trace, propagate
from .config import get_settings

logger = logging.getLogger(__name__)
B = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 80, 160)

# ---- API
API_REQS = Counter("api_requests_total", "HTTP requests", ["route", "method", "status"])
API_LAT = Histogram("api_request_seconds", "HTTP latency", ["route"], buckets=B)
RUNS_SUBMITTED = Counter("runs_submitted_total", "Runs accepted", ["cache"])
RUNS_REJECTED = Counter("runs_rejected_total", "Requests rejected at ingestion", ["reason"])
RATE_LIMITED = Counter("rate_limited_total", "429s", ["client_kind"])
QUEUE_DEPTH = Gauge("queue_depth", "Queue length", ["queue"])
# ---- index freshness (D2)
INDEX_CHUNKS = Gauge("index_chunks", "Chunks in index")
INDEX_BUILT_TS = Gauge("index_built_timestamp_seconds", "Index build time")
INDEX_THROUGHPUT = Gauge("index_build_chunks_per_second", "Ingest throughput")
# ---- agents (A6)
AGENT_RUNS = Counter("agent_runs_total", "Agent runs", ["agent", "outcome"])
STEP_LAT = Histogram("agent_step_seconds", "Per step latency", ["agent", "step"], buckets=B)
RUN_STEPS = Histogram("agent_run_steps", "Steps per run", ["agent"], buckets=(1, 2, 3, 5, 8, 13, 21, 34))
RUN_TOOLS = Histogram("agent_run_tool_calls", "Tool calls per run", ["agent"], buckets=(0, 1, 2, 3, 5, 8, 13, 21, 34))
AGENT_LAT = Histogram("agent_run_seconds", "Agent run latency", ["agent"], buckets=B)
RUN_E2E = Histogram("run_e2e_seconds", "Submission to final result", ["route"], buckets=B)
VERIFY = Counter("verification_total", "Verification outcomes", ["outcome"])
GUARD = Counter("guardrail_events_total", "Guardrail events", ["type"])
CACHE = Counter("cache_events_total", "Cache events", ["kind", "result"])
QUALITY = Gauge("quality_score", "Latest sampled live quality score", ["metric"])
FEEDBACK = Counter("feedback_total", "Caller feedback", ["satisfactory"])
# ---- LLM (L5, A5)
LLM_CALLS = Counter("llm_calls_total", "LLM calls", ["step", "outcome"])
LLM_RETRIES = Counter("llm_retries_total", "LLM retries", ["step"])
LLM_LAT = Histogram("llm_call_seconds", "LLM call latency", ["step"], buckets=B)
LLM_TOKENS = Counter("llm_tokens_total", "Tokens", ["step", "kind"])
LLM_COST = Counter("llm_cost_usd_total", "Cost", ["step"])
CB_STATE = Gauge("llm_circuit_state", "0 closed, 1 half-open, 2 open")
CB_TRIPS = Counter("llm_circuit_open_total", "Breaker openings")

_tracer = None


def init_tracing(service: str):
    global _tracer
    s = get_settings()
    if s.otel_enabled and s.otel_endpoint:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        p = TracerProvider(resource=Resource.create({"service.name": service}))
        p.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_endpoint.rstrip("/") + "/v1/traces")))
        trace.set_tracer_provider(p)
    _tracer = trace.get_tracer("fssai-label")


def tracer():
    return _tracer or trace.get_tracer("fssai-label")


def inject_context() -> dict:
    c: dict = {}
    propagate.inject(c)
    return c


def extract_context(carrier: dict):
    return propagate.extract(carrier or {})


class Step:
    def __init__(self, inputs):
        self.inputs = inputs or {}
        self.out: dict = {}

    def set(self, **kw):
        self.out.update(kw)


class TraceRecorder:
    """Records every tool call / LLM call / verification of a run so it can be reconstructed from the run id."""

    def __init__(self, redis, run_id: str, agent: str, prompt_version: str):
        self.r, self.run_id, self.agent, self.pv = redis, run_id, agent, prompt_version
        self.steps = 0
        self.tool_calls = 0
        self.llm_calls = 0
        self.cost = 0.0
        self.ptok = 0
        self.ctok = 0
        self.t0 = time.perf_counter()

    def _push(self, ev: dict):
        try:
            k = f"trace:{self.run_id}"
            self.r.rpush(k, json.dumps(ev, default=str))
            self.r.expire(k, 7 * 86400)
        except Exception:  # tracing must never fail a run
            logger.warning("trace push failed", exc_info=True)

    def event(self, kind: str, name: str, **data):
        self._push({"ts": round(time.time(), 3), "run_id": self.run_id, "agent": self.agent, "kind": kind,
                    "name": name, "prompt_version": self.pv, **data})

    @contextmanager
    def step(self, kind: str, name: str, inputs: dict | None = None):
        st = Step(inputs)
        t = time.perf_counter()
        with tracer().start_as_current_span(f"{self.agent}.{kind}.{name}") as span:
            span.set_attribute("run_id", self.run_id)
            span.set_attribute("agent", self.agent)
            try:
                yield st
            except Exception as e:
                st.out["error"] = repr(e)[:300]
                span.record_exception(e)
                raise
            finally:
                dt = time.perf_counter() - t
                self.steps += 1
                if kind == "tool":
                    self.tool_calls += 1
                if kind == "llm":
                    self.llm_calls += 1
                    self.cost += st.out.get("cost_usd", 0) or 0
                    self.ptok += st.out.get("prompt_tokens", 0) or 0
                    self.ctok += st.out.get("completion_tokens", 0) or 0
                STEP_LAT.labels(self.agent, f"{kind}:{name}").observe(dt)
                self._push({"ts": round(time.time(), 3), "run_id": self.run_id, "agent": self.agent, "kind": kind,
                            "name": name, "prompt_version": self.pv, "inputs": st.inputs, "outputs": st.out,
                            "latency_ms": round(dt * 1000, 1)})

    def finish(self, outcome: str):
        AGENT_RUNS.labels(self.agent, outcome).inc()
        RUN_STEPS.labels(self.agent).observe(self.steps)
        RUN_TOOLS.labels(self.agent).observe(self.tool_calls)
        AGENT_LAT.labels(self.agent).observe(time.perf_counter() - self.t0)

    def stats(self) -> dict:
        return {"steps": self.steps, "tool_calls": self.tool_calls, "llm_calls": self.llm_calls,
                "latency_s": round(time.perf_counter() - self.t0, 3), "cost_usd": round(self.cost, 6),
                "prompt_tokens": self.ptok, "completion_tokens": self.ctok}
