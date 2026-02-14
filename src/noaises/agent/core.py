"""Agent core — one-shot query to Claude via the Agent SDK.

Uses query() for each interaction so the system prompt can be rebuilt
per turn with fresh memory context. We maintain conversation history
in our own memory module — the SDK doesn't hold state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    query,
)

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


def create_options(system_prompt: str) -> ClaudeAgentOptions:
    """Create agent options with a dynamic system prompt."""
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="acceptEdits",
    )


async def query_agent(user_text: str, system_prompt: str) -> str:
    """Send a one-shot query to Claude. Returns the full text response."""
    options = create_options(system_prompt)
    response_parts: list[str] = []

    async for message in query(prompt=user_text, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    response_parts.append(block.text)

    return "\n".join(response_parts)


async def query_agent_interruptible(
    user_text: str,
    system_prompt: str,
    interrupt: InterruptController,
) -> tuple[str, bool]:
    """Send a query to Claude with poll-based interruption.

    Checks interrupt.is_interrupted between each streaming message.
    Returns (response_text, was_interrupted).
    """
    options = create_options(system_prompt)
    response_parts: list[str] = []
    interrupted = False

    async for message in query(prompt=user_text, options=options):
        if interrupt.is_interrupted:
            interrupted = True
            break
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    response_parts.append(block.text)

    return "\n".join(response_parts), interrupted
