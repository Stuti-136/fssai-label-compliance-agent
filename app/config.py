"""Runtime configuration. Everything environment-specific comes from env vars (D4).
No credentials, endpoints or model identifiers are defaulted here."""
from __future__ import annotations
import os
from functools import lru_cache


def _s(n, d=None):
    v = os.environ.get(n)
    return v if v not in (None, "") else d


def _b(n, d):
    return str(_s(n, d)).lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self):
        self.service_name = _s("SERVICE_NAME", "app")
        self.log_level = _s("LOG_LEVEL", "INFO")
        self.redis_url = _s("REDIS_URL")
        # LLM provider (OpenAI-compatible chat API). Unset base URL => LLM disabled => deterministic fallback.
        self.llm_base_url = _s("LLM_BASE_URL")
        self.llm_model = _s("LLM_MODEL")
        self.llm_api_key = _s("LLM_API_KEY", "none")
        self.llm_timeout_s = float(_s("LLM_TIMEOUT_S", 15))
        self.llm_max_retries = int(_s("LLM_MAX_RETRIES", 2))
        self.llm_backoff_base_s = float(_s("LLM_BACKOFF_BASE_S", 0.5))
        self.cb_failure_threshold = int(_s("CB_FAILURE_THRESHOLD", 4))
        self.cb_reset_s = float(_s("CB_RESET_S", 30))
        self.price_prompt_per_1k = float(_s("LLM_PRICE_PROMPT_PER_1K", 0))
        self.price_completion_per_1k = float(_s("LLM_PRICE_COMPLETION_PER_1K", 0))
        # Retrieval
        self.embedding_backend = _s("EMBEDDING_BACKEND", "st")  # st | hash
        self.embedding_model = _s("EMBEDDING_MODEL")
        self.index_dir = _s("INDEX_DIR", "/data/index")
        self.corpus_dir = _s("CORPUS_DIR", "corpus/raw")
        self.retrieval_mode = _s("RETRIEVAL_MODE", "agentic")  # agentic | single_pass
        # Prompts
        self.prompt_version = _s("PROMPT_VERSION", "v1")
        # Agent budgets (A1)
        self.run_max_steps = int(_s("RUN_MAX_STEPS", 25))
        self.run_max_tool_calls = int(_s("RUN_MAX_TOOL_CALLS", 30))
        self.research_timeout_s = float(_s("RESEARCH_TIMEOUT_S", 60))
        self.assess_timeout_s = float(_s("ASSESS_TIMEOUT_S", 40))
        self.run_deadline_s = float(_s("RUN_DEADLINE_S", 180))
        self.max_attempts = int(_s("WORKER_MAX_ATTEMPTS", 2))
        self.worker_concurrency = int(_s("WORKER_CONCURRENCY", 4))
        self.metrics_port = int(_s("METRICS_PORT", 8001))
        # Cache / rate limit (D7)
        self.cache_enabled = _b("CACHE_ENABLED", "true")
        self.cache_ttl_s = int(_s("CACHE_TTL_S", 3600))
        self.rate_limit_per_min = int(_s("RATE_LIMIT_PER_MIN", 30))
        # Safety / testing
        self.allow_fault_injection = _b("ALLOW_FAULT_INJECTION", "false")
        self.quality_sample_rate = float(_s("QUALITY_SAMPLE_RATE", 0.2))
        # Observability
        self.otel_enabled = _b("OTEL_ENABLED", "false")
        self.otel_endpoint = _s("OTEL_EXPORTER_OTLP_ENDPOINT")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings():
    get_settings.cache_clear()
