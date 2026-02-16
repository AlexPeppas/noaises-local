"""Personality distiller — evolves companion personality every N turns.

Mirrors ``memory/distiller.py``. Runs in the background via
``asyncio.create_task``. Uses Haiku to analyze recent conversation and
current personality state, then returns a full-state replacement for the
evolution fields.
"""

from __future__ import annotations

import json

import anthropic

from noaises.config import settings
from noaises.memory.model import FullMemoryContext
from noaises.memory.store import MemoryStore
from noaises.personality.engine import (
    MAX_COMPANION_GUESSES,
    MAX_LEARNED_TRAITS,
    MAX_TONE_ADJUSTMENTS,
    PersonalityEngine,
)
from noaises.sessions.engine import SessionEngine

PERSONALITY_DISTILLATION_PROMPT = """\
You are a personality analysis assistant. Given a recent conversation between a \
user and their AI companion, plus the companion's current personality evolution \
state and memory context, produce an updated personality evolution state.

Use the Big Five personality dimensions (Openness, Conscientiousness, \
Extraversion, Agreeableness, Neuroticism) as a behavioral lens — describe \
observations in natural language, not numeric scores.

Return a JSON object with exactly these keys:
{{
  "tone_adjustments": ["<concise instruction for the companion's tone>", ...],
  "learned_traits": ["<observed user preference or behavioral pattern>", ...],
  "companion_guesses": [
    {{"guess": "<hypothesis about the user>", "confidence": "low|moderate|high", "since": "YYYY-MM-DD"}},
    ...
  ]
}}

Rules:
- This is a FULL STATE REPLACEMENT — return the complete desired state, not deltas.
- Preserve entries from the current state that are still valid.
- For companion_guesses, keep the original "since" date if a guess carries forward. \
Adjust "confidence" up or down as evidence accumulates or contradicts.
- Remove guesses that are clearly wrong based on new evidence.
- Consolidate redundant or overlapping entries — prefer fewer, higher-quality entries.
- tone_adjustments: max {max_tone} entries. Short imperative instructions for the \
companion (e.g. "be more concise when user is busy", "lean into technical depth").
- learned_traits: max {max_traits} entries. Observed preferences, habits, or patterns \
(e.g. "prefers code examples over abstractions", "likes dry humor").
- companion_guesses: max {max_guesses} entries. Working hypotheses — NOT facts. \
Frame as "likely...", "seems to...", "probably...".
- Output ONLY the JSON object, no markdown fences, no commentary.
""".format(
    max_tone=MAX_TONE_ADJUSTMENTS,
    max_traits=MAX_LEARNED_TRAITS,
    max_guesses=MAX_COMPANION_GUESSES,
)


async def distill_personality(
    personality: PersonalityEngine,
    full_memory: FullMemoryContext,
    session: SessionEngine,
    store: MemoryStore,
) -> None:
    """Run background personality distillation (fire-and-forget safe)."""
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

        # 3. Build context
        current_state = json.dumps(
            {
                "tone_adjustments": personality.evolution.get("tone_adjustments", []),
                "learned_traits": personality.evolution.get("learned_traits", []),
                "companion_guesses": personality.evolution.get("companion_guesses", []),
            },
            indent=2,
        )
        memory_state = store.build_memory_state(full_memory)

        user_message = (
            f"## Current Personality Evolution State\n```json\n{current_state}\n```\n\n"
            f"## Current Memory State\n{memory_state}\n\n"
            f"## Recent Conversation\n{transcript}"
        )

        # 4. Call Haiku for analysis
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model=settings.memory_distill_model,
            max_tokens=1024,
            system=PERSONALITY_DISTILLATION_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = response.content[0].text.strip()

        # 5. Strip markdown code fences if present
        if raw_text.startswith("```"):
            first_newline = raw_text.index("\n") if "\n" in raw_text else len(raw_text)
            raw_text = raw_text[first_newline + 1 :]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].rstrip()

        # 6. Parse and apply
        result = json.loads(raw_text)
        personality.apply_evolution(result)

        n_tone = len(result.get("tone_adjustments", []))
        n_traits = len(result.get("learned_traits", []))
        n_guesses = len(result.get("companion_guesses", []))
        print(
            f"[personality] Evolved: {n_tone} tone, {n_traits} traits, {n_guesses} guesses."
        )

    except json.JSONDecodeError as e:
        print(f"[personality] Failed to parse distillation response: {e}")
    except Exception as e:
        print(f"[personality] Error during distillation: {e}")
