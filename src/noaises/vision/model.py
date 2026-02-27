"""Vision model — moondream2 for describing the user from camera frames."""

from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

logger = logging.getLogger(__name__)

_QUERY_PROMPT = (
    "Describe the person visible. Focus on emotional state, facial expression, "
    "posture, gestures. Be concise (2-3 sentences). If no person visible, say so briefly."
)


class VisionModel:
    """Wraps moondream2 for single-frame description of the user.

    Uses the most recent frame from the buffer (best snapshot of user's
    current state when they finish speaking). Lazy-loaded on first use.
    Model stays loaded after camera_off to avoid reload latency.
    """

    def __init__(self, model_name: str = "vikhyatk/moondream2"):
        self._model_name = model_name
        self._model = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load moondream2 model. Uses bfloat16 on GPU, float32 on CPU."""
        import torch
        from transformers import AutoModelForCausalLM

        if torch.cuda.is_available():
            dtype = torch.bfloat16
            device_map = {"": "cuda"}
            print("[vision] Loading moondream2 on CUDA (bfloat16)")
        else:
            dtype = torch.float32
            device_map = {"": "cpu"}
            print("[vision] Loading moondream2 on CPU (float32)")

        self._model = AutoModelForCausalLM.from_pretrained(
            self._model_name,
            revision="2025-01-09",
            trust_remote_code=True,
            dtype=dtype,
            device_map=device_map,
        )
        self._loaded = True
        print(f"[vision] moondream2 ready")

    async def describe_frames(self, frames: list[np.ndarray]) -> str:
        """Pick the last frame and describe it asynchronously."""
        return await asyncio.to_thread(self._describe_blocking, frames)

    def _describe_blocking(self, frames: list[np.ndarray]) -> str:
        """Run moondream2 inference on the most recent frame."""
        import cv2
        from PIL import Image

        if not frames:
            return ""

        t0 = time.perf_counter()

        # Use the last frame — best snapshot of user's state when they stopped speaking
        frame = frames[-1]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)

        result = self._model.query(pil_image, _QUERY_PROMPT)
        description = result["answer"].strip()

        elapsed = time.perf_counter() - t0
        print(f"[vision] Inference complete in {elapsed:.1f}s")

        return description

    def unload(self) -> None:
        """Free model, clear CUDA cache."""
        self._model = None
        self._loaded = False

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        logger.info("Vision model unloaded")
