"""Persistent memory store — Markdown-based two-tier (short-term + long-term).

Short-term: daily working context in ``memory/short_term/{date}.md``
Long-term:  persistent knowledge in ``memory/long_term.md``

Both tiers use Markdown with ``## category`` headers and ``- item`` lists.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from noaises.memory.model import (
    FullMemoryContext,
    LongTermMemory,
    ShortTermMemory,
)


class MemoryStore:
    """Markdown-based two-tier memory persistence."""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.short_term_dir = memory_dir / "short_term"
        self.long_term_path = memory_dir / "long_term.md"

        self.short_term_dir.mkdir(parents=True, exist_ok=True)

    # ── Load / Save ────────────────────────────────────────────────

    def load_full_memory(self) -> FullMemoryContext:
        """Load both tiers from disk into an in-memory FullMemoryContext."""
        return FullMemoryContext(
            short_term=self._load_short_term(),
            long_term=self._load_long_term(),
        )

    def save_all(self, memory: FullMemoryContext) -> None:
        """Persist both tiers to disk."""
        self._save_short_term(memory.short_term)
        self._save_long_term(memory.long_term)

    # ── Short-term ────────────────────────────────────────────────

    def _short_term_path(self, day: str | None = None) -> Path:
        day = day or date.today().isoformat()
        return self.short_term_dir / f"{day}.md"

    def _load_short_term(self) -> ShortTermMemory:
        today = date.today().isoformat()
        path = self._short_term_path(today)
        if not path.exists():
            return ShortTermMemory(date=today)
        categories = _parse_markdown_to_categories(path.read_text(encoding="utf-8"))
        return ShortTermMemory(date=today, categories=categories)

    def _save_short_term(self, memory: ShortTermMemory) -> None:
        content = _serialize_short_term_to_markdown(memory)
        self._short_term_path(memory.date).write_text(content, encoding="utf-8")

    # ── Long-term ─────────────────────────────────────────────────

    def _load_long_term(self) -> LongTermMemory:
        if not self.long_term_path.exists():
            return LongTermMemory()
        categories = _parse_markdown_to_categories(
            self.long_term_path.read_text(encoding="utf-8")
        )
        return LongTermMemory(categories=categories)

    def _save_long_term(self, memory: LongTermMemory) -> None:
        content = _serialize_long_term_to_markdown(memory)
        self.long_term_path.write_text(content, encoding="utf-8")

    # ── System-prompt helper ──────────────────────────────────────

    def build_memory_state(self, memory: FullMemoryContext) -> str:
        """Build a formatted memory-state string for the system prompt."""
        lines: list[str] = []

        if not memory.long_term.is_empty():
            lines.append("### About This User (Long-Term)")
            for category, items in memory.long_term.categories.items():
                lines.append(f"**{category}:** " + " | ".join(items))

        if not memory.short_term.is_empty():
            lines.append(f"\n### Today ({memory.short_term.date}) (Short-Term)")
            for category, items in memory.short_term.categories.items():
                lines.append(f"**{category}:** " + " | ".join(items))

        if not lines:
            return "_No memories stored yet._"

        return "\n".join(lines)


# ── Markdown serialization ────────────────────────────────────────


def _serialize_short_term_to_markdown(memory: ShortTermMemory) -> str:
    lines = [f"# Short-Term Memory: {memory.date}", ""]
    if not memory.categories:
        lines.append("_No memories stored yet_")
    else:
        for category, items in sorted(memory.categories.items()):
            lines.append(f"## {category}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    return "\n".join(lines) + "\n"


def _serialize_long_term_to_markdown(memory: LongTermMemory) -> str:
    lines = ["# Long-Term Memory", ""]
    if not memory.categories:
        lines.append("_No memories stored yet_")
    else:
        for category, items in sorted(memory.categories.items()):
            lines.append(f"## {category}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")
    return "\n".join(lines) + "\n"


# ── Markdown parsing ──────────────────────────────────────────────


def _parse_markdown_to_categories(content: str) -> dict[str, list[str]]:
    """Parse Markdown with ``## category`` headers and ``- item`` lists."""
    categories: dict[str, list[str]] = {}
    current_category: str | None = None

    for line in content.split("\n"):
        line = line.strip()

        # Skip top-level headings, blanks, and italic placeholders
        if (
            not line
            or line.startswith("# ")
            or (line.startswith("_") and line.endswith("_"))
        ):
            continue

        # Category header
        if line.startswith("## "):
            current_category = line[3:].strip()
            if current_category not in categories:
                categories[current_category] = []

        # List item
        elif line.startswith("- ") and current_category:
            item = line[2:].strip()
            if item:
                categories[current_category].append(item)

    return categories
