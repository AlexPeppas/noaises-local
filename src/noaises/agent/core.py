"""Agent core — one-shot query to Claude via the Agent SDK.

Uses query() for each interaction so the system prompt can be rebuilt
per turn with fresh memory context. We maintain conversation history
in our own memory module — the SDK doesn't hold state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator

from ..config import settings
from ..logger import log
from ..resources import get_claude_cli_path
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ClaudeSDKClient,
)
from claude_agent_sdk.types import StreamEvent
from claude_agent_sdk._errors import CLIConnectionError

if TYPE_CHECKING:
    from noaises.interrupt.controller import InterruptController


@dataclass
class AgentStreamEvent:
    """Event emitted by stream_agent_deltas().

    kind:
      - "text_delta"  — a chunk of assistant text (``text`` is set)
      - "tool_use"    — agent is invoking a tool (``tool_name`` is set)
      - "tool_result" — tool execution finished
      - "done"        — stream ended (``full_response`` has accumulated text)
    """

    kind: str  # text_delta | thinking_delta | tool_use | tool_result | done
    text: str = ""
    thinking: str = ""
    tool_name: str = ""
    full_response: str = ""
    was_interrupted: bool = False


ALLOWED_TOOLS = [
    "Task",
    "Bash",
    "Glob",
    "Grep",
    "Read",
    "Edit",
    "Write",
    "WebFetch",
    "WebSearch",
]


def create_options(
    system_prompt: str,
    mcp_servers: dict[str, Any] | None = None,
    extra_allowed_tools: list[str] | None = None,
    include_partial_messages: bool = False,
) -> ClaudeAgentOptions:
    """Create agent options with a dynamic system prompt and optional MCP servers."""
    allowed = ALLOWED_TOOLS + (extra_allowed_tools or [])
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=allowed,
        model="claude-opus-4-5",
        fallback_model="claude-sonnet-4-5",
        permission_mode="acceptEdits",
        mcp_servers=mcp_servers or {},
        setting_sources=["project"],
        cwd=settings.noaises_home_resolved,
        include_partial_messages=include_partial_messages,
        cli_path=get_claude_cli_path(),
    )


def _is_transport_cleanup_error(exc: BaseException) -> bool:
    """Check if an exception is the SDK transport cleanup race condition.

    The SDK spawns MCP control-request handlers as background tasks via
    ``start_soon``. When the query generator exits, ``close()`` cancels the
    task group — but a lingering handler may try to write after the transport
    is already closed, raising ``CLIConnectionError``. The actual response
    has already been collected, so this is safe to swallow.
    """
    if isinstance(exc, ExceptionGroup):
        return all(_is_transport_cleanup_error(e) for e in exc.exceptions)
    return isinstance(exc, CLIConnectionError) and "not ready for writing" in str(exc)


async def query_agent(
    user_text: str,
    system_prompt: str,
    mcp_servers: dict[str, Any] | None = None,
    extra_allowed_tools: list[str] | None = None,
) -> str:
    """Send a one-shot query to Claude. Returns the full text response."""
    options = create_options(system_prompt, mcp_servers, extra_allowed_tools)
    response_parts: list[str] = []

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_text)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_parts.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            response_parts.append(f"I'll use {block.name}")

    except BaseException as exc:
        if _is_transport_cleanup_error(exc) and response_parts:
            pass  # Response already collected, transport cleanup race — safe to ignore
        else:
            raise

    return "\n".join(response_parts)


async def query_agent_interruptible(
    user_text: str,
    system_prompt: str,
    interrupt: InterruptController,
    mcp_servers: dict[str, Any] | None = None,
    extra_allowed_tools: list[str] | None = None,
    surface: Any | None = None,
) -> tuple[str, bool]:
    """Send a query to Claude with poll-based interruption.

    Checks interrupt.is_interrupted between each streaming message.
    Returns (response_text, was_interrupted).
    """
    options = create_options(system_prompt, mcp_servers, extra_allowed_tools)
    response_parts: list[str] = []
    interrupted = False

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_text)

            async for message in client.receive_response():
                if interrupt.is_interrupted:
                    interrupted = True
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            response_parts.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            (
                                log(
                                    "INFO",
                                    f"[TOOL] invoking {block.name}",
                                    {
                                        "toolInput": block.input,
                                    },
                                ),
                            )
                            if block.name == "WebSearch":
                                if surface:
                                    surface.set_state("searching")
                        elif isinstance(block, ToolResultBlock):
                            log("INFO", f"[TOOL] tool result {block.content}", {})

    except BaseException as exc:
        if _is_transport_cleanup_error(exc) and response_parts:
            pass  # Response already collected, transport cleanup race — safe to ignore
        else:
            raise

    return "\n".join(response_parts), interrupted


async def query_stream_agent_interruptible(
    user_text: str,
    system_prompt: str,
    interrupt: InterruptController,
    mcp_servers: dict[str, Any] | None = None,
    extra_allowed_tools: list[str] | None = None,
) -> AsyncGenerator[AgentStreamEvent, None]:
    """Async generator that yields per-token deltas from the Claude agent.

    Enables streaming TTS and typewriter-style console output. Uses
    ``include_partial_messages=True`` so the SDK emits ``StreamEvent``
    objects containing raw Anthropic API events (``content_block_delta``
    with ``text_delta``).

    Yields:
        AgentStreamEvent with kind in {text_delta, tool_use, tool_result, done}.
    """
    options = create_options(
        system_prompt,
        mcp_servers,
        extra_allowed_tools,
        include_partial_messages=True,
    )
    accumulated_text: list[str] = []

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_text)

            async for message in client.receive_response():
                if interrupt.is_interrupted:
                    yield AgentStreamEvent(
                        kind="done",
                        full_response="".join(accumulated_text),
                        was_interrupted=True,
                    )
                    return

                # --- Raw streaming token from Anthropic API ---
                if isinstance(message, StreamEvent):
                    event = message.event
                    event_type = event.get("type", "")
                    if event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type", "")
                        if delta_type == "text_delta":
                            token = delta.get("text", "")
                            if token:
                                accumulated_text.append(token)
                                yield AgentStreamEvent(kind="text_delta", text=token)
                        elif delta_type == "thinking_delta":
                            thinking = delta.get("thinking", "")
                            if thinking:
                                yield AgentStreamEvent(
                                    kind="thinking_delta", thinking=thinking
                                )

                # --- Full message (tool use / tool result blocks) ---
                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            log(
                                "INFO",
                                f"[TOOL] invoking {block.name}",
                                {"toolInput": block.input},
                            )
                            yield AgentStreamEvent(
                                kind="tool_use", tool_name=block.name
                            )
                        elif isinstance(block, ToolResultBlock):
                            log(
                                "INFO",
                                f"[TOOL] tool result {block.content}",
                                {},
                            )
                            yield AgentStreamEvent(kind="tool_result")
                        # TextBlock — skip, already covered by text_delta events

    except BaseException as exc:
        if _is_transport_cleanup_error(exc) and accumulated_text:
            pass  # Response already collected, transport cleanup race — safe to ignore
        else:
            raise

    yield AgentStreamEvent(
        kind="done",
        full_response="".join(accumulated_text),
    )
