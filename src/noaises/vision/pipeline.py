"""Vision pipeline — orchestrates camera capture and vision model."""

from __future__ import annotations

import asyncio
import logging

from noaises.vision.camera import CameraCapture
from noaises.vision.model import VisionModel

logger = logging.getLogger(__name__)


class VisionPipeline:
    """Coordinates CameraCapture and VisionModel lifecycle.

    - ``start()`` loads the model (if needed) and opens the camera.
    - ``stop()`` closes the camera but keeps the model loaded.
    - ``flush_and_describe()`` grabs buffered frames and runs inference.
    - ``shutdown()`` releases everything (camera + model).
    """

    def __init__(
        self,
        device_index: int = 0,
        frame_interval: float = 0.5,
        model_name: str = "vikhyatk/moondream2",
    ):
        self._camera = CameraCapture(device_index, frame_interval)
        self._model = VisionModel(model_name)

    @property
    def is_active(self) -> bool:
        return self._camera.is_active

    @property
    def pending_frame_count(self) -> int:
        return self._camera.pending_frame_count

    async def start(self) -> str:
        """Load model if needed, start camera, capture initial frame and describe.

        Returns a status message with an immediate visual description so the
        agent has real data on the first turn (not just "camera is on").
        """
        if not self._model.is_loaded:
            logger.info("Loading vision model (first use)...")
            await asyncio.to_thread(self._model.load)

        await asyncio.to_thread(self._camera.start)

        # Wait briefly for the first frame, then describe it immediately
        await asyncio.sleep(0.6)
        frames = self._camera.flush()
        if frames:
            description = await self._model.describe_frames(frames)
            return f"Camera is now on. Here is what you see: {description}"

        return "Camera is now on but no frame was captured yet. You'll see the user on the next turn."

    async def stop(self) -> str:
        """Stop camera. Model stays loaded for fast restart."""
        self._camera.stop()
        return "Camera is now off."

    async def flush_and_describe(self) -> str | None:
        """Flush buffered frames and describe them. Returns None if camera inactive."""
        if not self._camera.is_active:
            return None

        frames = self._camera.flush()
        if not frames:
            return None

        return await self._model.describe_frames(frames)

    def shutdown(self) -> None:
        """Full cleanup — stop camera and unload model."""
        self._camera.stop()
        self._model.unload()
        logger.info("Vision pipeline shut down")
