"""FastAPI proxy: Anthropic Messages API -> Ollama (OpenAI Chat Completions API).

Accepts requests in Anthropic format, translates to OpenAI format, forwards
to Ollama, translates responses back. Supports both streaming (SSE) and batch.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .translator import (
    StreamState,
    parse_sse_line,
    translate_request,
    translate_response,
    translate_stream_chunk,
)
from ..config import settings

app = FastAPI(
    title="noaises-proxy", description="Anthropic -> Ollama translation proxy"
)


def _ollama_chat_url() -> str:
    return f"{settings.ollama_base_url}/v1/chat/completions"


def _model_map() -> dict[str, str]:
    """Build model mapping from settings. All Claude models -> local model."""
    local = settings.local_model_name
    return {
        "claude-opus-4-5": local,
        "claude-sonnet-4-5": local,
        "claude-haiku-4-5-20251001": local,
    }


# ---------------------------------------------------------------------------
# POST /v1/messages — main proxy endpoint
# ---------------------------------------------------------------------------


@app.post("/v1/messages")
async def messages(request: Request) -> Any:
    body = await request.json()
    anthropic_model = body.get("model", "claude-sonnet-4-5")
    is_stream = body.get("stream", False)
    model_map = _model_map()

    openai_body = translate_request(body, model_map)

    if is_stream:
        return StreamingResponse(
            _stream_response(openai_body, anthropic_model),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _batch_response(openai_body, anthropic_model)


def _ollama_error_response(exc: Exception) -> JSONResponse:
    """Return a clear Anthropic-shaped error when Ollama is unreachable."""
    return JSONResponse(
        status_code=502,
        content={
            "type": "error",
            "error": {
                "type": "api_error",
                "message": (
                    f"Proxy cannot reach Ollama at {settings.ollama_base_url}. "
                    f"Is 'ollama serve' running? ({type(exc).__name__}: {exc})"
                ),
            },
        },
    )


async def _batch_response(
    openai_body: dict[str, Any],
    anthropic_model: str,
) -> JSONResponse:
    """Forward a non-streaming request to Ollama and translate back."""
    openai_body["stream"] = False

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(_ollama_chat_url(), json=openai_body)
            resp.raise_for_status()
            openai_resp = resp.json()
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        return _ollama_error_response(exc)

    anthropic_resp = translate_response(openai_resp, anthropic_model)
    return JSONResponse(content=anthropic_resp)


async def _stream_response(
    openai_body: dict[str, Any],
    anthropic_model: str,
):
    """Stream SSE events from Ollama, translating each chunk to Anthropic format."""
    openai_body["stream"] = True
    state = StreamState(anthropic_model=anthropic_model)

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST", _ollama_chat_url(), json=openai_body
            ) as resp:
                resp.raise_for_status()
                buffer = ""
                async for raw_chunk in resp.aiter_text():
                    buffer += raw_chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        parsed = parse_sse_line(line)
                        if parsed is None:
                            continue
                        events = translate_stream_chunk(parsed, state)
                        for event in events:
                            yield event
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        # For streaming, yield an error event the Anthropic SDK can parse
        error_msg = (
            f"Proxy cannot reach Ollama at {settings.ollama_base_url}. "
            f"Is 'ollama serve' running? ({type(exc).__name__}: {exc})"
        )
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': error_msg}})}\n\n"


# ---------------------------------------------------------------------------
# POST /v1/messages/count_tokens — stub
# ---------------------------------------------------------------------------


@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> JSONResponse:
    """Rough token count estimate (~4 chars per token)."""
    body = await request.json()
    text = json.dumps(body.get("messages", []))
    system = body.get("system", "")
    if isinstance(system, list):
        system = json.dumps(system)
    total_chars = len(text) + len(str(system))
    return JSONResponse(content={"input_tokens": max(1, total_chars // 4)})


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_proxy():
    """Entry point for `uv run noaises-proxy`."""
    print(f"[proxy] Anthropic -> Ollama proxy starting on :{settings.proxy_port}")
    print(f"[proxy] Ollama backend: {settings.ollama_base_url}")
    print(f"[proxy] Model mapping: Claude -> {settings.local_model_name}")

    # Quick connectivity check
    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/version", timeout=3.0)
        print(
            f"[proxy] Ollama is reachable (version: {resp.json().get('version', '?')})"
        )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        print(
            f"[proxy] WARNING: Ollama is not reachable at {settings.ollama_base_url}. "
            "Make sure 'ollama serve' is running."
        )

    uvicorn.run(app, host="127.0.0.1", port=settings.proxy_port, log_level="info")
