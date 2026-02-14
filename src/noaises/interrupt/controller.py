"""Interrupt controller — thread-safe barge-in and stop support.

Uses both threading.Event (for cross-thread polling from blocking
sounddevice/TTS threads) and asyncio.Event (for async coroutine waiting).
"""

from __future__ import annotations

import asyncio
import enum
import threading


class InterruptSource(enum.Enum):
    BARGE_IN = "barge_in"
    SURFACE_CLICK = "surface_click"


class InterruptController:
    """Central coordinator for interrupt signals across threads.

    fire() is thread-safe — can be called from any thread (pywebview,
    sounddevice, etc.). is_interrupted is a cheap poll for blocking code.
    wait() is for async coroutines.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread_event = threading.Event()
        self._async_event = asyncio.Event()
        self._source: InterruptSource | None = None
        self._enabled = False

    @property
    def is_interrupted(self) -> bool:
        return self._thread_event.is_set()

    @property
    def source(self) -> InterruptSource | None:
        return self._source

    def enable(self) -> None:
        """Enable interrupt detection. Clears any prior signal."""
        self._thread_event.clear()
        self._async_event.clear()
        self._source = None
        self._enabled = True

    def disable(self) -> None:
        """Disable interrupt detection."""
        self._enabled = False

    def fire(self, source: InterruptSource) -> None:
        """Signal an interrupt. Thread-safe — callable from any thread."""
        if not self._enabled:
            return
        self._source = source
        self._thread_event.set()
        self._loop.call_soon_threadsafe(self._async_event.set)

    async def wait(self) -> InterruptSource:
        """Async wait until an interrupt fires. Returns the source."""
        await self._async_event.wait()
        return self._source  # type: ignore[return-value]
