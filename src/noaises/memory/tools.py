"""MCP server exposing memory_store and memory_remove tools to the agent.

The agent calls these tools during conversation to actively manage memory.
Tools close over a shared ``FullMemoryContext`` instance so mutations are
visible to the rest of the application.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from noaises.memory.model import FullMemoryContext

MEMORY_META_PROMPT = """\
## Memory System

You have two-tier memory (memory_store, memory_remove tools):
- **short_term** — daily working memory (tasks, context, blockers). Resets each day.
- **long_term** — persistent (profile, preferences, facts). Survives across sessions.

Guidelines:
- Do NOT just store conversation history — extract semantic facts and preferences.
- Store facts about the user naturally as you learn them.
- Keep memories current — remove outdated info, add new details as you learn them.
- Categories are dynamic — use whatever names make sense.
"""

MEMORY_TOOL_NAMES = [
    "mcp__memory__memory_store",
    "mcp__memory__memory_remove",
]


def create_memory_mcp_server(memory: FullMemoryContext) -> Any:
    """Create an in-process MCP server with memory tools bound to *memory*."""

    @tool(
        "memory_store",
        "Store or update a memory. Choose tier based on persistence needs.",
        {
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": ["short_term", "long_term"],
                    "description": "short_term = daily working context, long_term = persistent knowledge",
                },
                "category": {
                    "type": "string",
                    "description": "Dynamic category name (you decide)",
                },
                "content": {
                    "type": "string",
                    "description": "The fact or preference to remember",
                },
                "replaces": {
                    "type": "string",
                    "description": "Optional — old content to replace (partial match). Omit for new entries.",
                },
            },
            "required": ["tier", "category", "content"],
        },
    )
    async def memory_store(args: dict[str, Any]) -> dict[str, Any]:
        tier_name: str = args["tier"]
        category: str = args["category"]
        content: str = args["content"]
        replaces: str | None = args.get("replaces")

        target = memory.short_term if tier_name == "short_term" else memory.long_term

        if replaces:
            replaced = target.replace(category, replaces, content)
            if replaced:
                return _ok(f"Updated in {tier_name}/{category}: {content}")
            # If nothing to replace, just add
            target.add(category, content)
            return _ok(
                f"No match for '{replaces}' — added as new in {tier_name}/{category}: {content}"
            )

        target.add(category, content)
        return _ok(f"Stored in {tier_name}/{category}: {content}")

    @tool(
        "memory_remove",
        "Remove outdated or incorrect memory (partial match).",
        {
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": ["short_term", "long_term"],
                    "description": "Which tier to remove from",
                },
                "category": {
                    "type": "string",
                    "description": "Category to search in",
                },
                "content": {
                    "type": "string",
                    "description": "Content to remove (partial match)",
                },
            },
            "required": ["tier", "category", "content"],
        },
    )
    async def memory_remove(args: dict[str, Any]) -> dict[str, Any]:
        tier_name: str = args["tier"]
        category: str = args["category"]
        content: str = args["content"]

        target = memory.short_term if tier_name == "short_term" else memory.long_term
        removed = target.remove(category, content)

        if removed:
            return _ok(f"Removed from {tier_name}/{category}: {content}")
        return _ok(f"No match found in {tier_name}/{category} for: {content}")

    return create_sdk_mcp_server(
        name="memory",
        version="1.0.0",
        tools=[memory_store, memory_remove],
    )


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}
