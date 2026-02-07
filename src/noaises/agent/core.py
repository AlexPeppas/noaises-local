"""Agent core — one-shot query to Claude via the Agent SDK.

Uses query() for each interaction so the system prompt can be rebuilt
per turn with fresh memory context. We maintain conversation history
in our own memory module — the SDK doesn't hold state.
"""

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    query,
)

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
