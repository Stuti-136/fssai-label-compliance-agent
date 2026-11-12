"""Provider-agnostic LLM client with timeout, bounded retry + exponential backoff, circuit breaker (A5),
and per-call token/cost accounting (L5). Any OpenAI-compatible endpoint works; configured only via env."""
from __future__ import annotations
import json, random, re, threading, time, logging
from dataclasses import dataclass
import httpx
from .config import get_settings
from . import obs

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    pass


class CircuitOpen(LLMUnavailable):
    pass


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_s: float
    retries: int


class CircuitBreaker:
    CLOSED, HALF, OPEN = 0, 1, 2

    def __init__(self, threshold: int, reset_s: float):
        self.threshold, self.reset_s = threshold, reset_s
        self.state, self.failures, self.opened_at = self.CLOSED, 0, 0.0
        self.lock = threading.Lock()
        obs.CB_STATE.set(0)

    def allow(self) -> bool:
        with self.lock:
            if self.state == self.OPEN:
                if time.time() - self.opened_at >= self.reset_s:
                    self.state = self.HALF
                    obs.CB_STATE.set(1)
                    return True
                return False
            return True

    def ok(self):
        with self.lock:
            self.failures, self.state = 0, self.CLOSED
            obs.CB_STATE.set(0)

    def fail(self):
        with self.lock:
            self.failures += 1
            if self.state == self.HALF or self.failures >= self.threshold:
                if self.state != self.OPEN:
                    obs.CB_TRIPS.inc()
                    logger.warning("circuit breaker OPEN")
                self.state, self.opened_at = self.OPEN, time.time()
                obs.CB_STATE.set(2)


class LLMClient:
    def __init__(self):
        s = get_settings()
        self.s = s
        self.breaker = CircuitBreaker(s.cb_failure_threshold, s.cb_reset_s)
        self.http = httpx.Client(timeout=httpx.Timeout(s.llm_timeout_s, connect=3.0))

    @property
    def enabled(self) -> bool:
        return bool(self.s.llm_base_url and self.s.llm_model)

    def chat(self, system: str, user: str, step: str, max_tokens: int = 300) -> LLMResult:
        s = self.s
        if not self.enabled:
            obs.LLM_CALLS.labels(step, "disabled").inc()
            raise LLMUnavailable("LLM not configured")
        t0 = time.perf_counter()
        last: Exception | None = None
        for attempt in range(s.llm_max_retries + 1):
            if not self.breaker.allow():
                obs.LLM_CALLS.labels(step, "circuit_open").inc()
                raise CircuitOpen("circuit breaker open")
            try:
                r = self.http.post(
                    s.llm_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {s.llm_api_key}"},
                    json={"model": s.llm_model, "max_tokens": max_tokens, "temperature": 0,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"status {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                d = r.json()
                text = d["choices"][0]["message"]["content"] or ""
                u = d.get("usage") or {}
                pt = int(u.get("prompt_tokens") or (len(system) + len(user)) // 4)
                ct = int(u.get("completion_tokens") or len(text) // 4)
                cost = pt / 1000 * s.price_prompt_per_1k + ct / 1000 * s.price_completion_per_1k
                self.breaker.ok()
                lat = time.perf_counter() - t0
                obs.LLM_CALLS.labels(step, "ok").inc()
                obs.LLM_LAT.labels(step).observe(lat)
                obs.LLM_TOKENS.labels(step, "prompt").inc(pt)
                obs.LLM_TOKENS.labels(step, "completion").inc(ct)
                obs.LLM_COST.labels(step).inc(cost)
                return LLMResult(text, pt, ct, cost, lat, attempt)
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last = e
                self.breaker.fail()
                if attempt < s.llm_max_retries:
                    obs.LLM_RETRIES.labels(step).inc()
                    time.sleep(s.llm_backoff_base_s * (2 ** attempt) * (0.5 + random.random()))
        obs.LLM_CALLS.labels(step, "failed").inc()
        raise LLMUnavailable(f"LLM call failed after retries: {last!r}")


_client: LLMClient | None = None
_lock = threading.Lock()


def get_llm() -> LLMClient:
    global _client
    with _lock:
        if _client is None:
            _client = LLMClient()
        return _client


def reset_llm():
    global _client
    _client = None


def parse_json_loose(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None
