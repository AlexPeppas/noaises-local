"""Screen capture tool — lets noaises see the user's screen.

Captures the active monitor (the one with the mouse cursor) via `mss`,
saves a PNG to data/screenshots/, and returns the path so Claude can
Read the image and respond to visual context.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import mss
import mss.tools

# Patterns that signal the user wants noaises to look at their screen.
_SCREEN_PATTERNS = [
    re.compile(
        r"\b(?:check|look at|see|show|view|what(?:'s| is) on)\b.*\b(?:screen|desktop|monitor|display)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:check|see|look at|tell me)\b.*\bwhat (?:i'm|i am|im) (?:working|doing|looking)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:what(?:'s| is)|check)\b.*\b(?:working on|doing)\b.*\b(?:right now|at the moment|currently)\b",
        re.IGNORECASE,
    ),
]

_CLEANUP_AGE = timedelta(hours=1)


def _get_cursor_pos() -> tuple[int, int] | None:
    """Return (x, y) of the mouse cursor, or None if unavailable."""
    if sys.platform != "win32":
        return None
    try:
        pt = ctypes.wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return (pt.x, pt.y)
    except Exception:
        pass
    return None


def _active_monitor(monitors: list[dict]) -> dict:
    """Return the mss monitor dict that contains the mouse cursor.

    Falls back to the primary monitor (monitors[1]) if cursor position
    can't be determined or doesn't land on any known monitor.
    """
    cursor = _get_cursor_pos()
    if cursor:
        cx, cy = cursor
        # monitors[0] is the virtual combined screen — skip it
        for mon in monitors[1:]:
            if (
                mon["left"] <= cx < mon["left"] + mon["width"]
                and mon["top"] <= cy < mon["top"] + mon["height"]
            ):
                return mon
    # Fallback: primary monitor
    return monitors[1]


class CaptureScreenTool:
    """Captures the active monitor and saves screenshots for Claude to read."""

    def __init__(self, save_dir: Path):
        self._save_dir = save_dir
        self._save_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, surface=None) -> Path:
        """Capture the active monitor (where the cursor is), save as PNG.

        If *surface* is provided, briefly hides the persona window so it
        doesn't appear in the screenshot.
        """
        # Hide persona window so it's not in the screenshot
        hidden = False
        if surface and surface._window:
            surface._window.hide()
            hidden = True
            time.sleep(0.15)  # let the window fully disappear

        try:
            with mss.mss() as sct:
                monitor = _active_monitor(sct.monitors)
                raw = sct.grab(monitor)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = self._save_dir / f"screen_{timestamp}.png"
                mss.tools.to_png(raw.rgb, raw.size, output=str(path))
        finally:
            # Always restore the persona window
            if hidden:
                surface._window.show()

        self._cleanup_old()
        return path

    @staticmethod
    def detect_intent(user_input: str) -> bool:
        """Return True if the user's message implies they want a screen capture."""
        return any(p.search(user_input) for p in _SCREEN_PATTERNS)

    def _cleanup_old(self):
        """Delete screenshots older than 1 hour to prevent disk bloat."""
        cutoff = datetime.now() - _CLEANUP_AGE
        for png in self._save_dir.glob("screen_*.png"):
            try:
                if datetime.fromtimestamp(png.stat().st_mtime) < cutoff:
                    png.unlink()
            except OSError:
                pass
