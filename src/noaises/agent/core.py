"""Agent core — one-shot query to Claude via the Agent SDK.

Uses query() for each interaction so the system prompt can be rebuilt
per turn with fresh memory context. We maintain conversation history
in our own memory module — the SDK doesn't hold state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import settings
from ..logger import log
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ClaudeSDKClient
)
from claude_agent_sdk._errors import CLIConnectionError

if TYPE_CHECKING:
    from noaises.interrupt.controller import InterruptController

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
                            log("INFO",
                            f"[TOOL] invoking {block.name}",
                            {
                                "toolInput": block.input,
                            }),
                            if (block.name == "WebSearch"):
                                 if surface:
                                    surface.set_state("searching")
                        elif isinstance(block, ToolResultBlock):
                            log(
                            "INFO",
                            f"[TOOL] tool result {block.content}", {})
                            
    except BaseException as exc:
        if _is_transport_cleanup_error(exc) and response_parts:
            pass  # Response already collected, transport cleanup race — safe to ignore
        else:
            raise

    return "\n".join(response_parts), interrupted
