"""Vision model — Qwen2-VL-2B for describing user from camera video frames."""

from __future__ import annotations

import asyncio
import logging

import numpy as np

logger = logging.getLogger(__name__)

_DESCRIBE_PROMPT = (
    "Describe the person visible. Focus on emotional state, facial expression, "
    "posture, gestures. Be concise (2-3 sentences). If no person visible, say so briefly."
)


class VisionModel:
    """Wraps Qwen2-VL-2B via HuggingFace transformers for video frame description.

    Frames captured while the user speaks are treated as a single video clip.
    Lazy-loaded on first use. Model stays loaded after camera_off to avoid
    reload latency on next camera_on.
    """

    def __init__(
        self, model_name: str = "Qwen/Qwen2-VL-2B-Instruct", max_frames: int = 6
    ):
        self._model_name = model_name
        self._max_frames = max_frames
        self._model = None
        self._processor = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load model and processor. Uses 4-bit quantization on GPU if available."""
        import torch
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

        device_map = "auto"
        quantization_config = None

        if torch.cuda.is_available():
            try:
                from transformers import BitsAndBytesConfig

                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                )
                logger.info("Loading vision model with 4-bit quantization (GPU)")
            except ImportError:
                logger.info(
                    "bitsandbytes not available — loading vision model in float16"
                )
        else:
            logger.info("No GPU detected — loading vision model in float16 on CPU")
            device_map = "cpu"

        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            self._model_name,
            torch_dtype=torch.float16,
            device_map=device_map,
            quantization_config=quantization_config,
        )
        self._processor = AutoProcessor.from_pretrained(self._model_name)
        self._loaded = True
        print(f"[vision] Model loaded on device: {self._model.device}")

    async def describe_frames(self, frames: list[np.ndarray]) -> str:
        """Describe frames asynchronously (runs blocking inference in thread)."""
        return await asyncio.to_thread(self._describe_frames_blocking, frames)

    def _describe_frames_blocking(self, frames: list[np.ndarray]) -> str:
        """Run inference on buffered frames, treated as a video clip."""
        import time

        import torch
        from qwen_vl_utils import process_vision_info

        if not frames:
            return ""

        t0 = time.perf_counter()

        # Subsample to max_frames evenly spaced
        if len(frames) > self._max_frames:
            indices = np.linspace(0, len(frames) - 1, self._max_frames, dtype=int)
            frames = [frames[i] for i in indices]

        # Convert BGR (OpenCV) → RGB PIL Images (qwen_vl_utils expects PIL for video frames)
        import cv2
        from PIL import Image

        pil_frames = [
            Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)) for f in frames
        ]

        # Build as a single video input — list of PIL Images
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "video", "video": pil_frames, "fps": 2.0},
                    {"type": "text", "text": _DESCRIBE_PROMPT},
                ],
            }
        ]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self._model.device)

        print(f"[vision] Preprocessing done in {time.perf_counter() - t0:.1f}s, generating...")

        with torch.no_grad():
            generated_ids = self._model.generate(**inputs, max_new_tokens=150)

        # Trim input tokens from output
        generated_ids_trimmed = [
            out_ids[len(in_ids) :]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output = self._processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True
        )

        elapsed = time.perf_counter() - t0
        print(f"[vision] Inference complete in {elapsed:.1f}s")

        return output[0].strip() if output else ""

    def unload(self) -> None:
        """Free model and processor, clear CUDA cache."""
        self._model = None
        self._processor = None
        self._loaded = False

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        logger.info("Vision model unloaded")
