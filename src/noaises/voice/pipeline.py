"""Voice pipeline — captures audio, runs STT, and dispatches TTS.

Uses sounddevice for microphone capture with simple energy-based VAD
(voice activity detection) to know when the user stops speaking.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from noaises.voice.stt import STTProvider
    from noaises.voice.tts import TTSProvider

# Audio settings
SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "float32"

# VAD settings
SILENCE_THRESHOLD = 0.008  # RMS energy below this = silence (lowered for sensitivity)
SILENCE_DURATION = 1.5  # Seconds of silence before stopping
MAX_RECORD_SECONDS = 30  # Hard cap on recording length
CHUNK_DURATION = 0.1  # Seconds per read chunk


class VoicePipeline:
    """Manages audio capture (STT) and speech output (TTS)."""

    def __init__(self, stt: STTProvider, tts: TTSProvider):
        self.stt = stt
        self.tts = tts

    async def listen(self) -> str:
        """Capture audio from mic until silence, then transcribe."""
        try:
            audio = await self._capture_audio()
        except Exception as e:
            print(f"[voice] Audio capture error: {e}", file=sys.stderr)
            return ""

        if audio.size == 0:
            print("[voice] No speech detected, retrying...")
            return ""

        print(f"[voice] Captured {len(audio) / SAMPLE_RATE:.1f}s of audio, transcribing...")

        try:
            text = await self.stt.transcribe(audio, SAMPLE_RATE)
        except Exception as e:
            print(f"[voice] Transcription error: {e}", file=sys.stderr)
            return ""

        return text

    async def speak(self, text: str) -> None:
        """Send text to TTS provider."""
        await self.tts.speak(text)

    async def _capture_audio(self) -> np.ndarray:
        """Record from microphone until silence detected (energy-based VAD)."""
        import sounddevice as sd

        chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)
        max_chunks = int(MAX_RECORD_SECONDS / CHUNK_DURATION)
        silence_chunks_needed = int(SILENCE_DURATION / CHUNK_DURATION)

        def _record_blocking() -> np.ndarray:
            # List available devices for debugging on first call
            default_device = sd.query_devices(kind="input")
            print(f"[voice] Using input device: {default_device['name']}")
            print("[voice] Listening... (speak now)")

            chunks: list[np.ndarray] = []
            silence_count = 0
            has_speech = False
            peak_rms = 0.0

            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=chunk_samples,
            )
            stream.start()
            try:
                for i in range(max_chunks):
                    data, overflowed = stream.read(chunk_samples)
                    chunk = data[:, 0] if data.ndim > 1 else data.flatten()
                    rms = float(np.sqrt(np.mean(chunk**2)))

                    if rms > peak_rms:
                        peak_rms = rms

                    # Print RMS level periodically so user can see mic activity
                    if i % 10 == 0:  # Every 1 second
                        bar = "#" * min(int(rms * 500), 30)
                        status = "RECORDING" if has_speech else "waiting"
                        print(f"[voice] [{status}] RMS: {rms:.4f} |{bar}")

                    if rms > SILENCE_THRESHOLD:
                        has_speech = True
                        silence_count = 0
                        chunks.append(chunk)
                    elif has_speech:
                        silence_count += 1
                        chunks.append(chunk)
                        if silence_count >= silence_chunks_needed:
                            print("[voice] Silence detected, stopping capture.")
                            break
                    # If no speech yet, keep waiting
            finally:
                stream.stop()
                stream.close()

            if not has_speech:
                print(f"[voice] No speech detected (peak RMS: {peak_rms:.4f}, threshold: {SILENCE_THRESHOLD})")

            if chunks:
                return np.concatenate(chunks)
            return np.array([], dtype=np.float32)

        return await asyncio.to_thread(_record_blocking)
