"""Camera capture — daemon thread reads frames at interval, buffers for VAD flush."""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)


class CameraCapture:
    """Threaded camera capture that buffers frames between VAD flushes.

    Frames accumulate while the user speaks. When VAD fires silence,
    the voice pipeline calls ``flush()`` to grab all buffered frames.
    """

    def __init__(self, device_index: int = 0, frame_interval: float = 0.5):
        self._device_index = device_index
        self._frame_interval = frame_interval
        self._buffer: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cap = None  # cv2.VideoCapture (lazy import)
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def pending_frame_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    def start(self) -> None:
        """Open camera device and start capture thread."""
        import cv2

        self._cap = cv2.VideoCapture(self._device_index)
        if not self._cap.isOpened():
            self._cap = None
            raise RuntimeError(
                f"Cannot open camera device {self._device_index}. "
                "Check that a camera is connected and not in use by another app."
            )

        # Cap resolution to limit memory
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self._stop_event.clear()
        with self._lock:
            self._buffer.clear()

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        self._active = True
        logger.info("Camera started (device %d)", self._device_index)

    def _capture_loop(self) -> None:
        """Read frames at interval until stop is signaled."""
        while not self._stop_event.is_set():
            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Camera read failed — skipping frame")
                time.sleep(self._frame_interval)
                continue

            with self._lock:
                self._buffer.append(frame)

            self._stop_event.wait(timeout=self._frame_interval)

    def flush(self) -> list[np.ndarray]:
        """Atomically grab and clear the frame buffer."""
        with self._lock:
            frames = self._buffer
            self._buffer = []
        return frames

    def stop(self) -> None:
        """Stop capture thread and release camera device."""
        self._active = False
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        with self._lock:
            self._buffer.clear()

        logger.info("Camera stopped")
