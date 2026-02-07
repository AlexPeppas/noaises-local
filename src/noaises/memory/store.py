"""Persistent memory store — file-based short-term + long-term with consolidation.

Short-term: daily JSONL logs in data/short_term/
Long-term: consolidated knowledge in data/long_term.json
Consolidation: background task merges short-term → long-term via Claude.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class MemoryStore:
    """Local file-based memory with short-term logs and long-term knowledge."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.short_term_dir = data_dir / "short_term"
        self.long_term_path = data_dir / "long_term.json"
        self.consolidation_state_path = data_dir / "consolidation_state.json"

        # Create directories
        self.short_term_dir.mkdir(parents=True, exist_ok=True)

        # Initialize long-term store if missing
        if not self.long_term_path.exists():
            self._write_json(self.long_term_path, {"entries": [], "last_updated": None})

        # Initialize consolidation state if missing
        if not self.consolidation_state_path.exists():
            self._write_json(
                self.consolidation_state_path,
                {"last_consolidated": None},
            )

    # ── Short-term ────────────────────────────────────────────────

    def append_short_term(
        self, role: str, text: str, tags: list[str] | None = None
    ):
        """Append an exchange to today's short-term JSONL log."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self.short_term_dir / f"{today}.jsonl"

        entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "role": role,
            "text": text,
        }
        if tags:
            entry["tags"] = tags

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_short_term_today(self) -> list[dict]:
        """Return today's short-term entries."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self.short_term_dir / f"{today}.jsonl"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def get_short_term_today_summary(self) -> str:
        """Return a formatted summary of today's conversation for the system prompt."""
        entries = self.get_short_term_today()
        if not entries:
            return ""
        # Keep the last 20 entries to avoid bloating the prompt
        recent = entries[-20:]
        lines = []
        for e in recent:
            role = "User" if e["role"] == "user" else "You"
            lines.append(f"- {role}: {e['text'][:200]}")
        return "\n".join(lines)

    # ── Long-term ─────────────────────────────────────────────────

    def _load_long_term(self) -> dict:
        return json.loads(self.long_term_path.read_text(encoding="utf-8"))

    def _save_long_term(self, data: dict):
        self._write_json(self.long_term_path, data)

    def get_long_term_context(
        self, query: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Return relevant long-term entries.

        If query is provided, do simple keyword matching. Otherwise return most recent.
        """
        data = self._load_long_term()
        entries = data.get("entries", [])

        if query and entries:
            query_lower = query.lower()
            keywords = query_lower.split()
            scored = []
            for entry in entries:
                content_lower = entry.get("content", "").lower()
                score = sum(1 for kw in keywords if kw in content_lower)
                if score > 0:
                    scored.append((score, entry))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [e for _, e in scored[:limit]]

        # No query — return most recent
        return entries[-limit:]

    def get_long_term_summary(self) -> str:
        """Return a formatted text summary of long-term memory for system prompt."""
        entries = self.get_long_term_context(limit=30)
        if not entries:
            return "No long-term memories yet."

        by_category: dict[str, list[str]] = {}
        for e in entries:
            cat = e.get("category", "general")
            by_category.setdefault(cat, []).append(e["content"])

        lines = []
        category_labels = {
            "fact": "Facts about the user",
            "preference": "User preferences",
            "learning": "Things learned",
            "personality_observation": "Personality observations",
        }
        for cat, items in by_category.items():
            label = category_labels.get(cat, cat.title())
            lines.append(f"### {label}")
            for item in items:
                lines.append(f"- {item}")
        return "\n".join(lines)

    def add_long_term(self, entries: list[dict]):
        """Add consolidated entries to long-term store."""
        data = self._load_long_term()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for entry in entries:
            data["entries"].append(
                {
                    "id": str(uuid.uuid4()),
                    "category": entry.get("category", "general"),
                    "content": entry["content"],
                    "confidence": entry.get("confidence", 0.8),
                    "created": today,
                    "source_dates": entry.get("source_dates", [today]),
                }
            )

        data["last_updated"] = now
        self._save_long_term(data)

    # ── Consolidation ─────────────────────────────────────────────

    async def consolidation_loop(self, interval_hours: float = 10.0):
        """Background task: periodically consolidate short-term → long-term."""
        while True:
            await asyncio.sleep(interval_hours * 3600)
            try:
                await self._consolidate()
            except Exception as e:
                print(f"[memory] Consolidation error: {e}")

    async def _consolidate(self):
        """Read unconsolidated short-term entries, extract facts via Claude,
        write to long-term, update consolidation state."""
        import anthropic

        state = json.loads(
            self.consolidation_state_path.read_text(encoding="utf-8")
        )
        last_ts = state.get("last_consolidated")

        # Gather all short-term entries since last consolidation
        all_entries: list[dict] = []
        for jsonl_file in sorted(self.short_term_dir.glob("*.jsonl")):
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if last_ts and entry["ts"] <= last_ts:
                    continue
                all_entries.append(entry)

        if not all_entries:
            return

        # Build the conversation log for Claude
        log_text = "\n".join(
            f"[{e['ts']}] {e['role']}: {e['text']}" for e in all_entries
        )

        prompt = (
            "You are a memory consolidation agent. Given a log of recent interactions "
            "between a user and an AI companion, extract:\n"
            "- Facts about the user (name, job, preferences, habits)\n"
            "- User preferences (communication style, topics of interest, dislikes)\n"
            "- Key learnings (what worked well, what frustrated the user)\n"
            "- Personality observations (how should the companion adapt its personality)\n\n"
            "Return as a JSON array of {\"category\", \"content\", \"confidence\"} objects.\n"
            "Categories: fact, preference, learning, personality_observation\n"
            "Confidence: 0.0 to 1.0\n"
            "Only extract genuinely useful information. Skip small talk and routine exchanges.\n"
            "Return ONLY the JSON array, no other text.\n\n"
            f"--- Interaction Log ---\n{log_text}"
        )

        client = anthropic.Anthropic()
        response = await asyncio.to_thread(
            client.messages.create,
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        response_text = response.content[0].text.strip()
        # Handle potential markdown code block wrapping
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])

        try:
            extracted = json.loads(response_text)
        except json.JSONDecodeError:
            print(f"[memory] Failed to parse consolidation response: {response_text[:200]}")
            return

        if extracted:
            self.add_long_term(extracted)
            print(f"[memory] Consolidated {len(extracted)} entries to long-term memory.")

        # Update consolidation state
        self._write_json(
            self.consolidation_state_path,
            {"last_consolidated": all_entries[-1]["ts"]},
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _write_json(path: Path, data: dict):
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
