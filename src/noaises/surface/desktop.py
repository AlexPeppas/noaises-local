"""Desktop UI surface — animated persona window using pywebview.

Launches a frameless, always-on-top, transparent window with a CSS-animated
persona character. Python <-> JS communication via the pywebview JS API bridge.

pywebview MUST run on the main thread (Windows requirement), so the async
event loop runs in a background thread instead.
"""

from __future__ import annotations

from pathlib import Path


class DesktopSurface:
    """Manages the always-on-top persona window."""

    def __init__(self, html_dir: Path):
        self._html_dir = html_dir
        self._state = "idle"
        self._window = None

    @property
    def state(self) -> str:
        return self._state

    def run_blocking(self):
        """Start the webview window. Blocks the calling thread (must be main thread).

        Call this from the main thread AFTER starting the async loop
        in a background thread.
        """
        import webview

        self._window = webview.create_window(
            "noaises",
            url=str(self._html_dir / "index.html"),
            width=250,
            height=320,
            frameless=True,
            on_top=True,
            transparent=True,
            background_color="#000000",
            js_api=self,
        )
        webview.start()

    def set_state(self, state: str):
        """Update animation state: idle, listening, thinking, searching, speaking."""
        self._state = state
        if self._window:
            self._window.evaluate_js(f"setPersonaState('{state}')")

    # -- JS API bridge (called from JavaScript) --

    def get_state(self) -> str:
        """Called from JS to get current state."""
        return self._state
