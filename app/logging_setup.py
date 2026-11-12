"""Structured JSON logging with a correlation id carried across services and agent steps (D5)."""
from __future__ import annotations
import contextvars, json, logging, sys, time
from .config import get_settings

correlation_id = contextvars.ContextVar("correlation_id", default="-")
run_id_var = contextvars.ContextVar("run_id", default="-")
agent_var = contextvars.ContextVar("agent", default="-")


class JsonFormatter(logging.Formatter):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def format(self, r):
        d = {"ts": round(time.time(), 3), "level": r.levelname, "service": self.service, "logger": r.name,
             "msg": r.getMessage(), "correlation_id": correlation_id.get(), "run_id": run_id_var.get(),
             "agent": agent_var.get()}
        d.update(getattr(r, "extra_fields", {}) or {})
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, default=str)


def setup_logging(service: str):
    s = get_settings()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(s.log_level)
    for noisy in ("httpx", "httpcore", "urllib3", "faiss", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log(logger: logging.Logger, msg: str, level=logging.INFO, **fields):
    logger.log(level, msg, extra={"extra_fields": fields})
