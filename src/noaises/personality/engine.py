"""Personality engine — loads traits from TOML, builds system prompts, evolves over time."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

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
                "interaction_count": 0,
                "last_evolved": None,
            }
            self._save_evolution()

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

        # Format evolution adjustments
        evolution_section = ""
        adjustments = self.evolution.get("tone_adjustments", [])
        learned = self.evolution.get("learned_traits", [])
        if adjustments or learned:
            parts = []
            if adjustments:
                parts.append("- Tone adjustments: " + "; ".join(adjustments))
            if learned:
                parts.append("- Learned preferences: " + "; ".join(learned))
            evolution_section = "\n## Evolved Traits\n" + "\n".join(parts) + "\n"

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

    def evolve(self, observations: list[dict]):
        """Apply personality observations from memory consolidation.

        Each observation should have 'category' and 'content'.
        Only 'personality_observation' category entries are applied here.
        """
        from datetime import datetime, timezone

        for obs in observations:
            if obs.get("category") != "personality_observation":
                continue
            content = obs.get("content", "")
            if content and content not in self.evolution["learned_traits"]:
                self.evolution["learned_traits"].append(content)

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
