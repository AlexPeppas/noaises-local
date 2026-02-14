"""Deterministic memory distiller — extracts semantic facts every N turns.

Runs in the background via ``asyncio.create_task``. Uses Haiku (fast, cheap)
to parse recent session history and emit structured memory operations.
"""

from __future__ import annotations

import json

import anthropic

from noaises.config import settings
from noaises.memory.model import FullMemoryContext
from noaises.memory.store import MemoryStore
from noaises.sessions.engine import SessionEngine

DISTILLATION_SYSTEM_PROMPT = """\
You are a memory extraction assistant. Given a recent conversation between a user \
and their AI companion, plus the current memory state, extract semantic facts.

Output a JSON array of memory operations. Each element:
{
  "tier": "short_term" | "long_term",
  "category": "<dynamic category name>",
  "content": "<concise fact or preference>",
  "action": "add" | "remove"
}

Rules:
- Extract facts, preferences, and profile info — NOT raw conversation quotes.
- short_term: current tasks, blockers, context for today.
- long_term: user profile, preferences, facts, projects, technical context.
- If a fact is already in the current memory state, skip it.
- If a fact in current memory is outdated, emit a "remove" for the old and an "add" for the new.
- Prefer fewer, higher-quality entries over many low-value ones.
- Output ONLY the JSON array, no markdown fences, no commentary.
"""


def should_distill(turn_count: int) -> bool:
    """Check whether distillation should run for the current turn."""
    if not settings.memory_distill_enabled:
        return False
    return turn_count > 0 and turn_count % settings.memory_distill_interval == 0


async def distill_memories(
    full_memory: FullMemoryContext,
    session: SessionEngine,
    store: MemoryStore,
) -> None:
    """Run background memory distillation (fire-and-forget with asyncio.create_task)."""
    try:
        # 1. Load recent session entries
        entries = session.get_today()
        if not entries:
            return
        recent = entries[-20:]

        # 2. Build transcript
        transcript_lines: list[str] = []
        for entry in recent:
            role = "User" if entry["sender"] == "user" else "Assistant"
            transcript_lines.append(f"{role}: {entry['text']}")
        transcript = "\n\n".join(transcript_lines)

        # 3. Build current memory state
        current_state = store.build_memory_state(full_memory)

        user_message = (
            f"## Current Memory State\n{current_state}\n\n"
            f"## Recent Conversation\n{transcript}"
        )

        # 4. Call Haiku for extraction
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=settings.memory_distill_model,
            max_tokens=1024,
            system=DISTILLATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = response.content[0].text.strip()

        # 5. Strip markdown code fences if present
        if raw_text.startswith("```"):
            first_newline = raw_text.index("\n") if "\n" in raw_text else len(raw_text)
            raw_text = raw_text[first_newline + 1 :]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].rstrip()

        # 6. Parse and apply operations
        operations = json.loads(raw_text)
        applied = 0
        for op in operations:
            tier = op.get("tier")
            category = op.get("category")
            content = op.get("content")
            action = op.get("action", "add")

            if not tier or not category or not content:
                continue

            target = (
                full_memory.short_term
                if tier == "short_term"
                else full_memory.long_term
            )

            if action == "remove":
                target.remove(category, content)
            else:
                target.add(category, content)
            applied += 1

        # 7. Save to disk
        store.save_all(full_memory)
        print(
            f"[distill] Extracted {applied} memory operations from recent conversation."
        )

    except json.JSONDecodeError as e:
        print(f"[distill] Failed to parse distillation response: {e}")
    except Exception as e:
        print(f"[distill] Error during distillation: {e}")
