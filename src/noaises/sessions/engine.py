"""Session engine — append-only daily interaction logs.

Each day gets a JSONL file in the sessions directory. The SessionEngine
owns reading/writing these logs; the MemoryStore consolidation can read
them independently.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class SessionEngine:
    """Append-only daily session logs."""

    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _today_path(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.sessions_dir / f"{today}.jsonl"

    def append(self, sender: str, text: str, artifact: str | None = None):
        """Append an entry to today's session log."""
        entry: dict = {
            "sender": sender,
            "text": text,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if artifact:
            entry["artifact"] = artifact

        with open(self._today_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_today(self) -> list[dict]:
        """Return all entries from today's session."""
        path = self._today_path()
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def get_today_summary(self, limit: int = 20) -> str:
        """Return a formatted summary of recent session entries for the system prompt."""
        entries = self.get_today()
        if not entries:
            return ""
        recent = entries[-limit:]
        lines = []
        for e in recent:
            role = "User" if e["sender"] == "user" else "You"
            lines.append(f"- {role}: {e['text'][:200]}")
        return "\n".join(lines)
