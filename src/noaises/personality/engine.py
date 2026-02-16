"""Personality engine — loads traits from TOML, builds system prompts, evolves over time."""

from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

MAX_TONE_ADJUSTMENTS = 8
MAX_LEARNED_TRAITS = 12
MAX_COMPANION_GUESSES = 10

SYSTEM_PROMPT_TEMPLATE = """\
You are {name}, an autonomous AI companion that lives locally on the host's machine.

## Personality
- Tone: {tone}
- Verbosity: {verbosity}
- Traits: {traits}
{evolution_section}
{memory_guidance}
## What You Know About the User
{memory_context}

## Recent Context
{short_term_context}

## Guidelines
- You are speaking aloud — keep responses natural and conversational.
- Reference things you remember about the user when relevant.
- Stay in character. You are {name}, not "an AI assistant."
"""


class PersonalityEngine:
    """Loads personality config, builds system prompts, tracks evolution."""

    def __init__(self, config_path: Path, personality_dir: Path):
        self.config_path = config_path
        self.personality_dir = personality_dir
        self.evolution_path = personality_dir / "personality_evolution.json"

        # Load base personality from TOML
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)

        personality = raw.get("personality", {})
        self.name: str = personality.get("name", "LLL")
        self.tone: str = personality.get("tone", "friendly")
        self.verbosity: str = personality.get("verbosity", "concise")

        traits = personality.get("traits", {})
        self.traits: dict[str, str] = dict(traits)

        # Load or initialize evolution state
        if self.evolution_path.exists():
            self.evolution = json.loads(self.evolution_path.read_text(encoding="utf-8"))
        else:
            self.evolution = {
                "tone_adjustments": [],
                "learned_traits": [],
                "companion_guesses": [],
                "interaction_count": 0,
                "last_evolved": None,
            }
            self._save_evolution()

        # Migration for existing installs missing companion_guesses
        self.evolution.setdefault("companion_guesses", [])

    def build_system_prompt(
        self,
        memory_context: str,
        short_term_context: str = "",
        memory_guidance: str = "",
    ) -> str:
        """Build the full system prompt with personality + memory + evolution."""
        # Format traits
        trait_lines = (
            ", ".join(f"{k}: {v}" for k, v in self.traits.items())
            if self.traits
            else "none specified"
        )

        # Format evolution section
        evolution_section = ""
        adjustments = self.evolution.get("tone_adjustments", [])
        learned = self.evolution.get("learned_traits", [])
        guesses = self.evolution.get("companion_guesses", [])
        if adjustments or learned or guesses:
            parts = []
            if adjustments:
                parts.append("- Tone adjustments: " + "; ".join(adjustments))
            if learned:
                parts.append("- Learned preferences: " + "; ".join(learned))
            if guesses:
                guess_lines = []
                for g in guesses:
                    guess = g.get("guess", "")
                    confidence = g.get("confidence", "unknown")
                    since = g.get("since", "unknown")
                    guess_lines.append(
                        f"  - {guess} ({confidence} confidence, since {since})"
                    )
                parts.append(
                    "- Working hypotheses about the user:\n" + "\n".join(guess_lines)
                )
            evolution_section = "\n## Personality Evolution\n" + "\n".join(parts) + "\n"

        return SYSTEM_PROMPT_TEMPLATE.format(
            name=self.name,
            tone=self.tone,
            verbosity=self.verbosity,
            traits=trait_lines,
            evolution_section=evolution_section,
            memory_guidance=memory_guidance,
            memory_context=memory_context
            or "Nothing yet — this is a new relationship.",
            short_term_context=short_term_context or "No recent conversation.",
        )

    def record_interaction(self):
        """Increment interaction count and persist."""
        self.evolution["interaction_count"] += 1
        self._save_evolution()

    def apply_evolution(self, result: dict):
        """Apply a full-state evolution result from the personality distiller.

        *result* is the complete desired state — not a delta. Keys:
        ``tone_adjustments``, ``learned_traits``, ``companion_guesses``.
        Each is capped to its maximum length.
        """
        if "tone_adjustments" in result:
            self.evolution["tone_adjustments"] = list(result["tone_adjustments"])[
                :MAX_TONE_ADJUSTMENTS
            ]
        if "learned_traits" in result:
            self.evolution["learned_traits"] = list(result["learned_traits"])[
                :MAX_LEARNED_TRAITS
            ]
        if "companion_guesses" in result:
            self.evolution["companion_guesses"] = list(result["companion_guesses"])[
                :MAX_COMPANION_GUESSES
            ]

        self.evolution["last_evolved"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        self._save_evolution()

    def _save_evolution(self):
        self.personality_dir.mkdir(parents=True, exist_ok=True)
        self.evolution_path.write_text(
            json.dumps(self.evolution, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
