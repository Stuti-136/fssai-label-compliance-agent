"""LLM stub (D6): OpenAI-compatible /v1/chat/completions that returns fixed responses after a realistic delay.
Used for load tests (so we measure OUR system, not the provider's rate limits) and as the default provider so the
stack runs from a clean clone with no API key.

Failure injection for the circuit-breaker demo:
  POST /admin/mode {"mode": "ok" | "down" | "error500" | "slow"}"""
import asyncio, json, os, random, time
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

DELAY_MS = float(os.environ.get("STUB_DELAY_MS", 800))
JITTER_MS = float(os.environ.get("STUB_JITTER_MS", 300))
app = FastAPI(title="llm-stub")
state = {"mode": "ok"}
CALLS = Counter("stub_calls_total", "stub calls", ["mode"])


@app.get("/healthz")
def healthz():
    return {"status": "ok", "mode": state["mode"]}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/admin/mode")
async def set_mode(req: Request):
    state["mode"] = (await req.json()).get("mode", "ok")
    return state


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    CALLS.labels(state["mode"]).inc()
    if state["mode"] == "down":
        return JSONResponse({"error": "unavailable"}, status_code=503)
    if state["mode"] == "error500":
        return JSONResponse({"error": "boom"}, status_code=500)
    d = DELAY_MS + random.uniform(-JITTER_MS, JITTER_MS)
    if state["mode"] == "slow":
        d = 60_000
    await asyncio.sleep(max(d, 0) / 1000)
    sysmsg = body["messages"][0]["content"].lower()
    text = '{"query": "nutrition claim conditions schedule per 100 g"}' if "search" in sysmsg or "query" in sysmsg \
        else '{"summary": "Fixed stub response."}'
    n_in = sum(len(m["content"]) for m in body["messages"]) // 4
    return {"id": "stub", "object": "chat.completion", "created": int(time.time()), "model": body.get("model", "stub"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": n_in, "completion_tokens": len(text) // 4, "total_tokens": n_in + len(text) // 4}}
