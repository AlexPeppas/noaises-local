"""Desktop UI surface — animated persona window using pywebview.

Launches a frameless, always-on-top, transparent window with a CSS-animated
persona character. Python <-> JS communication via the pywebview JS API bridge.

pywebview MUST run on the main thread (Windows requirement), so the async
event loop runs in a background thread instead.

Transparency fix: the window starts hidden and only becomes visible after
the page loads, avoiding the race where WebView2 paints a white frame first.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path


class DesktopSurface:
    """Manages the always-on-top persona window."""

    def __init__(self, html_dir: Path):
        self._html_dir = html_dir
        self._state = "idle"
        self._window = None
        self._on_closed_callback = None
        self._suppress_close = (
            False  # True while programmatically hidden (e.g. screen capture)
        )

    @property
    def state(self) -> str:
        return self._state

    def run_blocking(self, on_closed=None):
        """Start the webview window. Blocks the calling thread (must be main thread).

        Call this from the main thread AFTER starting the async loop
        in a background thread.

        on_closed: optional callback invoked when the window is closed by the user.
        """
        import webview

        self._on_closed_callback = on_closed

        self._window = webview.create_window(
            "noaises",
            url=str(self._html_dir / "index.html"),
            width=250,
            height=320,
            frameless=True,
            on_top=True,
            transparent=True,
            hidden=True,  # start hidden — show after transparency is applied
            background_color="#000000",
            js_api=self,
        )

        self._window.events.loaded += self._on_loaded
        self._window.events.closed += self._on_window_closed

        webview.start()

    def _on_loaded(self):
        """Show the window only after the page has fully loaded.

        This avoids the white flash from WebView2 painting before
        transparency is applied. We also re-apply transparency at the
        native WebView2 control level to fix the race condition where
        EnsureCoreWebView2Async resets DefaultBackgroundColor.
        """
        if not self._window:
            return

        # Re-apply transparency at the native WebView2 control level.
        # pywebview sets Color.Transparent BEFORE EnsureCoreWebView2Async,
        # which can reset it. By the time 'loaded' fires, init is complete.
        try:
            from System.Drawing import Color  # noqa: N813 — .NET naming

            self._window.gui.browser.webview.DefaultBackgroundColor = Color.Transparent
        except Exception:
            pass  # non-Windows or non-EdgeChromium — CSS fallback is enough

        # Force transparent background on the document
        self._window.evaluate_js("""
            document.documentElement.style.background = 'transparent';
            document.body.style.background = 'transparent';
        """)

        # Small delay to let the WebView2 compositor catch up
        time.sleep(0.15)

        self._window.show()

    def _on_window_closed(self):
        """Called when the user closes the window."""
        if self._suppress_close:
            return  # programmatic hide, not a real close
        if self._on_closed_callback:
            self._on_closed_callback()

    def destroy(self):
        """Close the webview window (call from any thread)."""
        if self._window:
            self._window.destroy()

    def set_state(self, state: str):
        """Update animation state: idle, listening, thinking, searching, speaking, sleeping, seeing, remembering.

        Non-blocking: dispatches evaluate_js on a daemon thread so the
        asyncio event loop is never stalled waiting for the webview's
        main thread to finish rendering.
        """
        self._state = state
        if self._window:
            threading.Thread(
                target=self._window.evaluate_js,
                args=(f"setPersonaState('{state}')",),
                daemon=True,
            ).start()

    # -- JS API bridge (called from JavaScript) --

    def get_state(self) -> str:
        """Called from JS to get current state."""
        return self._state
