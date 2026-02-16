"""Voice pipeline — captures audio, runs STT, and dispatches TTS.

Uses sounddevice for microphone capture with simple energy-based VAD
(voice activity detection) to know when the user stops speaking.
"""

from __future__ import annotations

import asyncio
import re
import sys
import threading
import time
from typing import TYPE_CHECKING, AsyncGenerator

import numpy as np

if TYPE_CHECKING:
    from noaises.agent.core import AgentStreamEvent
    from noaises.interrupt.controller import InterruptController
    from noaises.voice.stt import STTProvider
    from noaises.voice.tts import AzureTTS

# Audio settings
SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "float32"

# VAD settings
SILENCE_THRESHOLD = 0.008  # RMS energy below this = silence (lowered for sensitivity)
SILENCE_DURATION = 1.5  # Seconds of silence before stopping
MAX_RECORD_SECONDS = 30  # Hard cap on recording length
CHUNK_DURATION = 0.1  # Seconds per read chunk

# Barge-in settings — tuned for headphone use (no speaker-to-mic bleed).
BARGE_IN_THRESHOLD = 0.02  # Lower OK with headphones — real speech is loud and clear
BARGE_IN_CONSECUTIVE = 4  # ~400ms sustained speech to confirm intent
BARGE_IN_ONSET_SKIP = 0.3  # Brief skip for mic open transient


# Regex: sentence-ending punctuation followed by whitespace (or end-of-string)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?:;])\s+|\n")


class SentenceBuffer:
    """Accumulates streaming tokens and flushes complete sentences.

    Sentence boundaries are detected at ``.!?:;`` followed by whitespace
    or ``\\n``.  This avoids feeding single tokens to TTS (choppy speech)
    while still streaming text as soon as a natural pause point arrives.
    """

    def __init__(self) -> None:
        self._buf = ""

    def add(self, text: str) -> list[str]:
        """Add a token; return any complete sentences ready to flush."""
        self._buf += text
        parts = _SENTENCE_BOUNDARY.split(self._buf)
        if len(parts) <= 1:
            return []  # no complete sentence yet
        # All but the last part are complete sentences
        sentences = parts[:-1]
        # reset buffer
        self._buf = parts[-1]
        return sentences

    def flush(self) -> str | None:
        """Return remaining buffered text (if any) and clear the buffer."""
        leftover = self._buf.strip()
        self._buf = ""
        return leftover or None


class VoicePipeline:
    """Manages audio capture (STT) and speech output (TTS)."""

    def __init__(self, stt: STTProvider, tts: AzureTTS):
        self.stt = stt
        self.tts = tts
        self._shutdown = threading.Event()

    def shutdown(self) -> None:
        """Signal all blocking operations to stop. Safe to call from any thread."""
        self._shutdown.set()
        self.tts.shutdown()

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
            # Normal completion — cancel the monitor; retrieve result to surface errors
            monitor_task.cancel()
            try:
                speak_task.result()
            except Exception as exc:
                print(f"[voice] TTS error: {exc}", file=sys.stderr)
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

    # Seconds to sleep after TTS finishes so residual speaker audio
    # dissipates before the next mic capture starts.
    _POST_TTS_COOLDOWN = 0.4

    async def speak_streaming(
        self,
        events: AsyncGenerator[AgentStreamEvent, None],
        interrupt: InterruptController,
        surface=None,
        personality_name: str = "LLL",
    ) -> tuple[str, bool]:
        """Consume an agent stream, printing tokens and feeding TTS in real time.

        Sentences are buffered and flushed to a ``StreamingTTSSession`` as
        they complete.  Console output is typewriter-style (token by token).

        Barge-in monitoring runs concurrently — tuned for headphone use
        (no speaker-to-mic bleed).  The user can interrupt by speaking
        over the assistant; sustained speech above the threshold fires
        the interrupt controller and stops TTS immediately.

        Returns ``(full_response, was_interrupted)``.
        """
        from noaises.voice.tts import StreamingTTSSession

        buf = SentenceBuffer()
        session: StreamingTTSSession | None = None
        full_response = ""
        was_interrupted = False
        first_token = True
        in_thinking = False

        # Barge-in monitor — started once TTS begins
        monitor_task: asyncio.Task | None = None

        try:
            async for event in events:
                if interrupt.is_interrupted:
                    was_interrupted = True
                    break

                if event.kind == "thinking_delta":
                    # Print thinking tokens to console (not spoken)
                    if not in_thinking:
                        in_thinking = True
                        print("\n  [thinking] ", end="", flush=True)
                    print(event.thinking, end="", flush=True)

                elif event.kind == "text_delta":
                    if in_thinking:
                        in_thinking = False
                        print()  # end thinking line

                    # First token: transition surface, start TTS stream, print name
                    if first_token:
                        first_token = False
                        print(f"\n{personality_name}: ", end="", flush=True)
                        if surface:
                            surface.set_state("speaking")
                        session = self.tts.create_stream_session()
                        session.start()
                        # Start barge-in monitoring
                        monitor_task = asyncio.create_task(
                            self._monitor_for_barge_in(interrupt)
                        )

                    # Typewriter console output
                    print(event.text, end="", flush=True)

                    # Buffer and flush complete sentences to TTS
                    sentences = buf.add(event.text)
                    if session:
                        for sentence in sentences:
                            session.write(sentence + " ")

                elif event.kind == "tool_use":
                    # Flush partial buffer before tool pause
                    if session:
                        leftover = buf.flush()
                        if leftover:
                            session.write(leftover + " ")
                    if surface:
                        state = (
                            "searching"
                            if event.tool_name == "WebSearch"
                            else "thinking"
                        )
                        surface.set_state(state)

                elif event.kind == "tool_result":
                    # Tool done — surface back to speaking if we had text before
                    if surface and not first_token:
                        surface.set_state("speaking")

                elif event.kind == "done":
                    full_response = event.full_response
                    was_interrupted = event.was_interrupted
                    break

            # Flush remaining buffer
            if session:
                leftover = buf.flush()
                if leftover:
                    session.write(leftover)
                session.close()

            print()  # newline after typewriter output

            # Wait for TTS audio to finish, racing against barge-in
            if session and not was_interrupted:
                wait_task = asyncio.create_task(session.wait())
                tasks_to_race = [wait_task]
                if monitor_task and not monitor_task.done():
                    tasks_to_race.append(monitor_task)

                done, pending = await asyncio.wait(
                    tasks_to_race, return_when=asyncio.FIRST_COMPLETED
                )

                if wait_task in done:
                    # TTS finished first — retrieve result (may be an error)
                    try:
                        wait_task.result()
                    except Exception as exc:
                        print(f"[voice] TTS stream error: {exc}", file=sys.stderr)
                else:
                    # Barge-in during audio tail — stop TTS
                    was_interrupted = True
                    session.stop()
                    wait_task.cancel()
                    try:
                        await wait_task
                    except (asyncio.CancelledError, Exception):
                        pass

                # Clean up remaining tasks
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

            # Brief cooldown so residual audio dissipates
            # before the next mic capture starts.
            if session:
                await asyncio.sleep(self._POST_TTS_COOLDOWN)

        except Exception as exc:
            print(f"\n[voice] Streaming speak error: {exc}", file=sys.stderr)
        finally:
            # Ensure TTS stream is closed and monitor cancelled on any exit
            if session:
                session.close()
            if monitor_task and not monitor_task.done():
                monitor_task.cancel()
                try:
                    await monitor_task
                except (asyncio.CancelledError, Exception):
                    pass

        return full_response, was_interrupted

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
                while not interrupt.is_interrupted and not self._shutdown.is_set():
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
                    if self._shutdown.is_set():
                        break
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
