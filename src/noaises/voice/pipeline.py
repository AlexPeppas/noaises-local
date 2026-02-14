"""Voice pipeline — captures audio, runs STT, and dispatches TTS.

Uses sounddevice for microphone capture with simple energy-based VAD
(voice activity detection) to know when the user stops speaking.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from noaises.interrupt.controller import InterruptController
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

# Barge-in settings (higher threshold to filter speaker bleed from TTS)
BARGE_IN_THRESHOLD = 0.04  # ~5x silence threshold — filters speaker bleed
BARGE_IN_CONSECUTIVE = 3  # Consecutive loud chunks needed (~300ms sustained)
BARGE_IN_ONSET_SKIP = 0.5  # Seconds to ignore at TTS start (onset burst)


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

        print(
            f"[voice] Captured {len(audio) / SAMPLE_RATE:.1f}s of audio, transcribing..."
        )

        try:
            text = await self.stt.transcribe(audio, SAMPLE_RATE)
        except Exception as e:
            print(f"[voice] Transcription error: {e}", file=sys.stderr)
            return ""

        return text

    async def speak(self, text: str) -> None:
        """Send text to TTS provider."""
        await self.tts.speak(text)

    async def speak_interruptible(
        self, text: str, interrupt: InterruptController
    ) -> None:
        """Speak text while monitoring for barge-in or external interrupt.

        Races TTS playback against barge-in detection. If either the
        monitor detects speech or an external interrupt fires, TTS is
        stopped immediately.
        """
        monitor_task = asyncio.create_task(self._monitor_for_barge_in(interrupt))
        speak_task = asyncio.create_task(self.tts.speak(text))

        done, pending = await asyncio.wait(
            [speak_task, monitor_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if speak_task in done:
            # Normal completion — cancel the monitor
            monitor_task.cancel()
        else:
            # Barge-in or external interrupt — stop TTS
            await self.tts.stop()
            speak_task.cancel()

        # Suppress CancelledError from pending tasks
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    async def _monitor_for_barge_in(self, interrupt: InterruptController) -> None:
        """Listen for user speech during TTS playback (barge-in detection).

        Opens a secondary sounddevice InputStream and checks for loud
        sustained audio that indicates the user is speaking over TTS.
        Uses a higher threshold than normal VAD to filter speaker bleed.
        """
        from noaises.interrupt.controller import InterruptSource

        def _monitor_blocking() -> bool:
            import sounddevice as sd

            chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION)
            consecutive_loud = 0
            start_time = time.monotonic()

            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=chunk_samples,
            )
            stream.start()
            try:
                while not interrupt.is_interrupted:
                    data, _ = stream.read(chunk_samples)
                    chunk = data[:, 0] if data.ndim > 1 else data.flatten()
                    rms = float(np.sqrt(np.mean(chunk**2)))

                    # Skip onset burst — TTS speaker can spike the mic
                    elapsed = time.monotonic() - start_time
                    if elapsed < BARGE_IN_ONSET_SKIP:
                        continue

                    if rms > BARGE_IN_THRESHOLD:
                        consecutive_loud += 1
                        if consecutive_loud >= BARGE_IN_CONSECUTIVE:
                            return True  # barge-in detected
                    else:
                        consecutive_loud = 0
            finally:
                stream.stop()
                stream.close()

            return False  # exited because of external interrupt

        detected = await asyncio.to_thread(_monitor_blocking)
        if detected:
            interrupt.fire(InterruptSource.BARGE_IN)

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
                print(
                    f"[voice] No speech detected (peak RMS: {peak_rms:.4f}, threshold: {SILENCE_THRESHOLD})"
                )

            if chunks:
                return np.concatenate(chunks)
            return np.array([], dtype=np.float32)

        return await asyncio.to_thread(_record_blocking)
