"""Speech-to-text providers."""

from __future__ import annotations

import asyncio
from typing import Protocol

import numpy as np


class STTProvider(Protocol):
    """Protocol for speech-to-text providers."""

    async def transcribe(self, audio: np.ndarray, sample_rate: int) -> str: ...


class WhisperSTT:
    """Local STT using faster-whisper (CTranslate2-based).

    Downloads the model on first run (~150MB for 'base').
    """

    def __init__(self, model_size: str = "base"):
        from faster_whisper import WhisperModel

        print(f"[stt] Loading Whisper model '{model_size}'...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("[stt] Whisper model ready.")

    async def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        """Transcribe audio array to text."""

        def _run():
            segments, info = self.model.transcribe(audio, language="en")
            # Consume the lazy generator inside the thread
            return " ".join(seg.text for seg in segments).strip()

        return await asyncio.to_thread(_run)
