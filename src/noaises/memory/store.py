"""Persistent memory store — file-based short-term + long-term with consolidation.

Short-term: daily JSONL working-context notes in memory/short_term/
  What the user is focused on, working on, or planning right now.
Long-term: consolidated knowledge in memory/long_term.json
Consolidation: background task merges sessions + short-term → long-term via Claude.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class MemoryStore:
    """Local file-based memory with short-term logs and long-term knowledge.

    Owns only the ``memory/`` directory. Session logs live in a sibling
    ``sessions/`` directory managed by ``SessionEngine``.
    """

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.short_term_dir = memory_dir / "short_term"
        self.long_term_path = memory_dir / "long_term.json"
        self.consolidation_state_path = memory_dir / "consolidation_state.json"

        # Sessions dir is a sibling — consolidation reads from there
        self.sessions_dir = memory_dir.parent / "sessions"

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

    def append_short_term(self, content: str, category: str = "general"):
        """Append a working-context entry to today's short-term memory.

        Short-term memory captures what the user is focused on, working on,
        or planning — semantic context, not raw conversation.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self.short_term_dir / f"{today}.jsonl"

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "content": content,
            "category": category,
        }

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_short_term_today(self) -> list[dict]:
        """Return today's short-term memory entries."""
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

    def get_short_term_summary(self, limit: int = 15) -> str:
        """Return a formatted summary of today's short-term memory for the system prompt."""
        entries = self.get_short_term_today()
        if not entries:
            return ""
        recent = entries[-limit:]
        lines = []
        for e in recent:
            cat = e.get("category", "general")
            lines.append(f"- [{cat}] {e['content'][:200]}")
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
        """Background task: periodically consolidate session logs → long-term."""
        while True:
            await asyncio.sleep(interval_hours * 3600)
            try:
                await self._consolidate()
            except Exception as e:
                print(f"[memory] Consolidation error: {e}")

    async def _consolidate(self):
        """Read unconsolidated session entries, extract facts via Claude,
        write to long-term, update consolidation state."""
        import anthropic

        state = json.loads(self.consolidation_state_path.read_text(encoding="utf-8"))
        last_ts = state.get("last_consolidated")

        # Gather session entries (conversation logs) since last consolidation
        session_entries: list[dict] = []
        if self.sessions_dir.exists():
            for jsonl_file in sorted(self.sessions_dir.glob("*.jsonl")):
                for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if last_ts and entry["ts"] <= last_ts:
                        continue
                    session_entries.append(entry)

        # Gather short-term memory entries (working context)
        short_term_entries: list[dict] = []
        for jsonl_file in sorted(self.short_term_dir.glob("*.jsonl")):
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if last_ts and entry["ts"] <= last_ts:
                    continue
                short_term_entries.append(entry)

        if not session_entries and not short_term_entries:
            return

        # Build the log for Claude — sessions as conversation, short-term as notes
        log_parts = []
        if session_entries:
            sender_key = "sender" if "sender" in session_entries[0] else "role"
            log_parts.append("--- Conversation Log ---")
            for e in session_entries:
                log_parts.append(f"[{e['ts']}] {e[sender_key]}: {e['text']}")
        if short_term_entries:
            log_parts.append("\n--- Working Context Notes ---")
            for e in short_term_entries:
                cat = e.get("category", "general")
                log_parts.append(f"[{e['ts']}] [{cat}] {e['content']}")
        log_text = "\n".join(log_parts)

        all_entries = session_entries + short_term_entries
        all_entries.sort(key=lambda e: e["ts"])

        prompt = (
            "You are a memory consolidation agent. Given a log of recent interactions "
            "between a user and an AI companion, plus any working-context notes about "
            "what the user is focused on, extract:\n"
            "- Facts about the user (name, job, preferences, habits)\n"
            "- User preferences (communication style, topics of interest, dislikes)\n"
            "- Key learnings (what worked well, what frustrated the user)\n"
            "- Personality observations (how should the companion adapt its personality)\n\n"
            'Return as a JSON array of {"category", "content", "confidence"} objects.\n'
            "Categories: fact, preference, learning, personality_observation\n"
            "Confidence: 0.0 to 1.0\n"
            "Only extract genuinely useful information. Skip small talk and routine exchanges.\n"
            "Working context notes are high-signal — they capture what the user is actively "
            "working on or planning. Weigh them accordingly.\n"
            "Return ONLY the JSON array, no other text.\n\n"
            f"{log_text}"
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
            print(
                f"[memory] Failed to parse consolidation response: {response_text[:200]}"
            )
            return

        if extracted:
            self.add_long_term(extracted)
            print(
                f"[memory] Consolidated {len(extracted)} entries to long-term memory."
            )

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
