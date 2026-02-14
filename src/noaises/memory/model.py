"""Two-tier dynamic memory model — short-term (daily) + long-term (persistent).

Categories are dynamic — Claude decides the category names. Storage is
Markdown with ``## category`` headers and ``- item`` lists.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class DynamicMemory(BaseModel):
    """Base class for dynamic-category memory."""

    categories: dict[str, list[str]] = Field(default_factory=dict)

    def add(self, category: str, content: str) -> None:
        """Add *content* under *category*, creating it if needed."""
        if category not in self.categories:
            self.categories[category] = []
        if content not in self.categories[category]:
            self.categories[category].append(content)

    def remove(self, category: str, content: str) -> bool:
        """Remove the first item that contains *content* (case-insensitive partial match).

        Returns True if something was removed.
        """
        if category not in self.categories:
            return False
        for i, item in enumerate(self.categories[category]):
            if content.lower() in item.lower():
                self.categories[category].pop(i)
                # Clean up empty categories
                if not self.categories[category]:
                    del self.categories[category]
                return True
        return False

    def replace(self, category: str, old: str, new: str) -> bool:
        """Replace the first item matching *old* (partial) with *new*."""
        if category not in self.categories:
            return False
        for i, item in enumerate(self.categories[category]):
            if old.lower() in item.lower():
                self.categories[category][i] = new
                return True
        return False

    def is_empty(self) -> bool:
        return not any(self.categories.values())


class ShortTermMemory(DynamicMemory):
    """Daily working memory — tasks, context, blockers. Resets each day."""

    date: str = Field(default_factory=lambda: date.today().isoformat())


class LongTermMemory(DynamicMemory):
    """Persistent knowledge — profile, preferences, facts. Survives across sessions."""

    pass


class FullMemoryContext(BaseModel):
    """Container for both memory tiers."""

    short_term: ShortTermMemory = Field(default_factory=ShortTermMemory)
    long_term: LongTermMemory = Field(default_factory=LongTermMemory)
