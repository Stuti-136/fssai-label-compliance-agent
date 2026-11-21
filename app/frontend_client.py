"""HTTP client helpers used by the Streamlit frontend."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx


class BackendError(RuntimeError):
    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or f"Backend returned HTTP {response.status_code}."

    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list):
            details = [
                f"{item.get('field', '$')}: {item.get('message', item.get('code', 'invalid'))}"
                for item in errors
                if isinstance(item, dict)
            ]
            if details:
                return "; ".join(details)
        return str(body.get("detail") or body.get("error") or body)
    return str(body)


def _check(response: httpx.Response) -> dict[str, Any]:
    if not response.is_success:
        raise BackendError(response.status_code, _error_message(response))
    try:
        body = response.json()
    except ValueError as exc:
        raise BackendError(response.status_code, "Backend returned invalid JSON.") from exc
    if not isinstance(body, dict):
        raise BackendError(response.status_code, "Backend returned an unexpected response.")
    return body


def assess_label(
    base_url: str,
    payload: dict[str, Any],
    *,
    timeout_s: float = 180,
    poll_interval_s: float = 1,
    on_status: Callable[[str], None] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[dict[str, Any], str]:
    """Submit a label and poll until its result is terminal or the local wait times out."""
    base = base_url.strip().rstrip("/")
    if not base:
        raise BackendError(None, "Set the FastAPI base URL before submitting.")
    deadline = time.monotonic() + timeout_s

    try:
        with httpx.Client(
            base_url=base + "/",
            timeout=httpx.Timeout(15, connect=5),
            transport=transport,
        ) as client:
            submission = _check(client.post("v1/runs", json=payload))
            run_id = submission.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise BackendError(None, "Backend accepted the request without returning a run ID.")

            while time.monotonic() < deadline:
                state = _check(client.get(f"v1/runs/{run_id}"))
                status = state.get("status")
                if not isinstance(status, str):
                    raise BackendError(None, "Backend run status response was malformed.")
                if on_status:
                    on_status(status)
                if status in {"completed", "failed"}:
                    result = state.get("result")
                    if not isinstance(result, dict):
                        raise BackendError(None, "The run ended without a result payload.")
                    return result, run_id
                time.sleep(max(0, min(poll_interval_s, deadline - time.monotonic())))
    except httpx.TimeoutException as exc:
        raise BackendError(None, "The backend request timed out. Check service health and try again.") from exc
    except httpx.RequestError as exc:
        raise BackendError(None, f"Could not reach the FastAPI backend: {exc}") from exc

    raise BackendError(None, f"Assessment is still running after {timeout_s:g} seconds.")


def get_trace(
    base_url: str,
    run_id: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    base = base_url.strip().rstrip("/")
    if not base:
        raise BackendError(None, "Set the FastAPI base URL before requesting evidence.")
    try:
        with httpx.Client(
            base_url=base + "/",
            timeout=httpx.Timeout(15, connect=5),
            transport=transport,
        ) as client:
            return _check(client.get(f"v1/runs/{run_id}/trace"))
    except httpx.TimeoutException as exc:
        raise BackendError(None, "The backend request timed out while loading evidence.") from exc
    except httpx.RequestError as exc:
        raise BackendError(None, f"Could not reach the FastAPI backend: {exc}") from exc


def get_readiness(
    base_url: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    base = base_url.strip().rstrip("/")
    if not base:
        raise BackendError(None, "Set the FastAPI base URL before checking service health.")
    try:
        with httpx.Client(
            base_url=base + "/",
            timeout=httpx.Timeout(5, connect=3),
            transport=transport,
        ) as client:
            return _check(client.get("readyz"))
    except httpx.TimeoutException as exc:
        raise BackendError(None, "The backend readiness check timed out.") from exc
    except httpx.RequestError as exc:
        raise BackendError(None, f"Could not reach the FastAPI backend: {exc}") from exc
