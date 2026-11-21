import httpx
import pytest

from app.frontend_client import BackendError, assess_label, get_trace


def test_assess_label_submits_polls_and_returns_result():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(202, json={"run_id": "run-123"})
        return httpx.Response(
            200,
            json={
                "run_id": "run-123",
                "status": "completed",
                "result": {"route": "revise-and-recheck", "findings": []},
            },
        )

    observed = []
    result, run_id = assess_label(
        "http://backend.test",
        {"product_name": "Biscuits"},
        poll_interval_s=0,
        on_status=observed.append,
        transport=httpx.MockTransport(handler),
    )

    assert run_id == "run-123"
    assert result["route"] == "revise-and-recheck"
    assert calls == ["/v1/runs", "/v1/runs/run-123"]
    assert observed == ["completed"]


def test_assess_label_surfaces_validation_details():
    def handler(request):
        return httpx.Response(
            422,
            json={
                "error": "validation_failed",
                "errors": [{"field": "product_name", "message": "Field required"}],
            },
        )

    with pytest.raises(BackendError, match="product_name: Field required"):
        assess_label(
            "http://backend.test",
            {},
            transport=httpx.MockTransport(handler),
        )


def test_get_trace_uses_run_specific_endpoint():
    def handler(request):
        assert request.url.path == "/v1/runs/run-456/trace"
        return httpx.Response(200, json={"passages_retrieved": []})

    trace = get_trace(
        "http://backend.test",
        "run-456",
        transport=httpx.MockTransport(handler),
    )

    assert trace["passages_retrieved"] == []
