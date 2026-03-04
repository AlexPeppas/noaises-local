"""Bidirectional translation between Anthropic Messages API and OpenAI Chat Completions API.

Anthropic (Claude) <-> OpenAI (Ollama/Qwen) format conversion for both
batch and streaming responses.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Model mapping
# ---------------------------------------------------------------------------

DEFAULT_MODEL_MAP: dict[str, str] = {
    "claude-opus-4-5": "qwen2.5:7b",
    "claude-sonnet-4-5": "qwen2.5:7b",
    "claude-haiku-4-5-20251001": "qwen2.5:7b",
}


def map_model(anthropic_model: str, model_map: dict[str, str] | None = None) -> str:
    mapping = model_map or DEFAULT_MODEL_MAP
    return mapping.get(anthropic_model, next(iter(mapping.values())))


# ---------------------------------------------------------------------------
# Request translation: Anthropic -> OpenAI
# ---------------------------------------------------------------------------


def _translate_system(system: str | list[dict] | None) -> str:
    """Extract system prompt text from Anthropic's system field."""
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    # list of content blocks
    parts: list[str] = []
    for block in system:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif "text" in block:
                parts.append(block["text"])
    return "\n".join(parts)


def _translate_content_blocks(content: str | list[dict]) -> str:
    """Convert Anthropic content blocks to a plain text string for OpenAI."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            btype = block.get("type", "text")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "image":
                parts.append("[image]")
    return "\n".join(parts)


def translate_request(
    body: dict[str, Any],
    model_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Translate an Anthropic Messages API request to OpenAI Chat Completions format."""
    openai_messages: list[dict[str, Any]] = []

    # System prompt
    system_text = _translate_system(body.get("system"))
    if system_text:
        openai_messages.append({"role": "system", "content": system_text})

    # Messages
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "user":
            # Content can be string or list of blocks
            if isinstance(content, str):
                openai_messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Check for tool_result blocks (these come in user messages in Anthropic API)
                text_parts: list[str] = []
                for block in content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype == "tool_result":
                            tool_content = block.get("content", "")
                            if isinstance(tool_content, list):
                                tool_content = "\n".join(
                                    b.get("text", "")
                                    for b in tool_content
                                    if isinstance(b, dict)
                                )
                            openai_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": block.get("tool_use_id", ""),
                                    "content": str(tool_content),
                                }
                            )
                        elif btype == "text":
                            text_parts.append(block.get("text", ""))
                        elif btype == "image":
                            text_parts.append("[image]")
                if text_parts:
                    openai_messages.append(
                        {"role": "user", "content": "\n".join(text_parts)}
                    )

        elif role == "assistant":
            if isinstance(content, str):
                openai_messages.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts = []
                tool_calls: list[dict[str, Any]] = []
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype == "text":
                            text_parts.append(block.get("text", ""))
                        elif btype == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block.get(
                                        "id", f"call_{uuid.uuid4().hex[:8]}"
                                    ),
                                    "type": "function",
                                    "function": {
                                        "name": block.get("name", ""),
                                        "arguments": json.dumps(block.get("input", {})),
                                    },
                                }
                            )
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if text_parts:
                    assistant_msg["content"] = "\n".join(text_parts)
                else:
                    assistant_msg["content"] = ""
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                openai_messages.append(assistant_msg)

    # Tools
    openai_tools: list[dict[str, Any]] | None = None
    if body.get("tools"):
        openai_tools = []
        for tool in body["tools"]:
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {}),
                    },
                }
            )

    # Build request
    result: dict[str, Any] = {
        "model": map_model(body.get("model", ""), model_map),
        "messages": openai_messages,
        "stream": body.get("stream", False),
    }

    if openai_tools:
        result["tools"] = openai_tools

    # Map parameters
    if "max_tokens" in body:
        result["max_tokens"] = body["max_tokens"]
    if "temperature" in body:
        result["temperature"] = body["temperature"]
    if "top_p" in body:
        result["top_p"] = body["top_p"]
    if "stop_sequences" in body:
        result["stop"] = body["stop_sequences"]

    return result


# ---------------------------------------------------------------------------
# Response translation: OpenAI -> Anthropic (batch)
# ---------------------------------------------------------------------------

FINISH_REASON_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def translate_response(
    openai_resp: dict[str, Any],
    anthropic_model: str,
) -> dict[str, Any]:
    """Translate an OpenAI Chat Completions response to Anthropic Messages format."""
    choice = openai_resp.get("choices", [{}])[0]
    message = choice.get("message", {})

    content: list[dict[str, Any]] = []

    # Text content
    text = message.get("content")
    if text:
        content.append({"type": "text", "text": text})

    # Tool calls
    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        try:
            tool_input = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            tool_input = {"raw": func.get("arguments", "")}
        content.append(
            {
                "type": "tool_use",
                "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                "name": func.get("name", ""),
                "input": tool_input,
            }
        )

    # If no content at all, add empty text
    if not content:
        content.append({"type": "text", "text": ""})

    # Usage
    usage_raw = openai_resp.get("usage", {})
    usage = {
        "input_tokens": usage_raw.get("prompt_tokens", 0),
        "output_tokens": usage_raw.get("completion_tokens", 0),
    }

    finish_reason = choice.get("finish_reason", "stop")
    stop_reason = FINISH_REASON_MAP.get(finish_reason, "end_turn")

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": anthropic_model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


# ---------------------------------------------------------------------------
# Streaming translation: OpenAI SSE -> Anthropic SSE
# ---------------------------------------------------------------------------


@dataclass
class StreamState:
    """Tracks state across streaming chunks for proper Anthropic event sequencing."""

    content_index: int = 0
    current_type: str = ""  # "text" or "tool_use"
    block_started: bool = False
    tool_call_ids: dict[int, str] = field(default_factory=dict)
    tool_call_names: dict[int, str] = field(default_factory=dict)
    tool_call_args: dict[int, str] = field(default_factory=dict)
    message_started: bool = False
    anthropic_model: str = ""
    input_tokens: int = 0


def make_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a single Anthropic SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def make_message_start_event(model: str) -> str:
    """Generate the initial message_start SSE event."""
    return make_sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": f"msg_{uuid.uuid4().hex[:24]}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )


def make_ping_event() -> str:
    return make_sse_event("ping", {"type": "ping"})


def translate_stream_chunk(
    chunk: dict[str, Any],
    state: StreamState,
) -> list[str]:
    """Translate a single OpenAI streaming chunk into Anthropic SSE events.

    Returns a list of formatted SSE event strings.
    """
    events: list[str] = []

    # Emit message_start on first chunk
    if not state.message_started:
        state.message_started = True
        events.append(make_message_start_event(state.anthropic_model))
        events.append(make_ping_event())

    choices = chunk.get("choices", [])
    if not choices:
        return events

    choice = choices[0]
    delta = choice.get("delta", {})
    finish_reason = choice.get("finish_reason")

    # --- Text delta ---
    text = delta.get("content")
    if text is not None:
        if state.current_type != "text" or not state.block_started:
            # Close previous block if switching types
            if state.block_started:
                events.append(
                    make_sse_event(
                        "content_block_stop",
                        {
                            "type": "content_block_stop",
                            "index": state.content_index,
                        },
                    )
                )
                state.content_index += 1

            # Start new text block
            events.append(
                make_sse_event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": state.content_index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )
            state.current_type = "text"
            state.block_started = True

        events.append(
            make_sse_event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": state.content_index,
                    "delta": {"type": "text_delta", "text": text},
                },
            )
        )

    # --- Tool call deltas ---
    tool_calls = delta.get("tool_calls", [])
    for tc in tool_calls:
        tc_index = tc.get("index", 0)
        func = tc.get("function", {})
        tc_id = tc.get("id")
        tc_name = func.get("name")
        tc_args = func.get("arguments", "")

        if tc_id:
            state.tool_call_ids[tc_index] = tc_id
        if tc_name:
            state.tool_call_names[tc_index] = tc_name
        if tc_args:
            state.tool_call_args.setdefault(tc_index, "")
            state.tool_call_args[tc_index] += tc_args

        # Start tool_use block when we get the name
        if tc_name:
            if state.block_started:
                events.append(
                    make_sse_event(
                        "content_block_stop",
                        {
                            "type": "content_block_stop",
                            "index": state.content_index,
                        },
                    )
                )
                state.content_index += 1

            tool_use_id = state.tool_call_ids.get(
                tc_index, f"toolu_{uuid.uuid4().hex[:12]}"
            )
            events.append(
                make_sse_event(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": state.content_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": tc_name,
                            "input": {},
                        },
                    },
                )
            )
            state.current_type = "tool_use"
            state.block_started = True

        # Stream argument fragments as input_json_delta
        if tc_args and state.block_started and state.current_type == "tool_use":
            events.append(
                make_sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": state.content_index,
                        "delta": {"type": "input_json_delta", "partial_json": tc_args},
                    },
                )
            )

    # --- Finish ---
    if finish_reason is not None:
        if state.block_started:
            events.append(
                make_sse_event(
                    "content_block_stop",
                    {
                        "type": "content_block_stop",
                        "index": state.content_index,
                    },
                )
            )

        stop_reason = FINISH_REASON_MAP.get(finish_reason, "end_turn")
        events.append(
            make_sse_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": 0},
                },
            )
        )
        events.append(make_sse_event("message_stop", {"type": "message_stop"}))

    return events


def parse_sse_line(line: str) -> dict[str, Any] | None:
    """Parse a single SSE data line from an OpenAI streaming response."""
    line = line.strip()
    if not line or not line.startswith("data: "):
        return None
    data = line[6:]
    if data == "[DONE]":
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None
