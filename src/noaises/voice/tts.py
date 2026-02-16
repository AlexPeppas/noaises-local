"""Text-to-speech providers."""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Protocol

import azure.cognitiveservices.speech as speechsdk


# Regex patterns for sanitizing text before TTS ingestion.
# Strip emoji and markdown so the synthesizer gets clean prose.
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols extended-A
    "\U00002702-\U000027b0"  # dingbats
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"  # zero-width joiner
    "]+",
    flags=re.UNICODE,
)
_MARKDOWN_RE = re.compile(r"(\*{1,2}|_{1,2}|`{1,3}|~{2})")


def _sanitize_for_tts(text: str) -> str:
    """Strip emoji and markdown formatting so Azure TTS gets clean text."""
    text = _EMOJI_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    return text


class TTSProvider(Protocol):
    """Protocol for text-to-speech providers."""

    async def speak(self, text: str) -> None: ...

    async def stop(self) -> None: ...


class StreamingTTSSession:
    """A streaming TTS session using queued ``speak_text_async()`` calls.

    Each ``write()`` fires a separate ``speak_text_async()``; the Azure SDK
    queues them internally and plays audio in order. Audio starts after the
    first sentence arrives — no TextStream/V2 endpoint needed.

    Call ``close()`` when done writing, then ``wait()`` to block until all
    queued audio has finished playing.
    """

    def __init__(
        self,
        synthesizer: speechsdk.SpeechSynthesizer,
        on_error=None,
    ):
        self._synthesizer = synthesizer
        self._futures: list[speechsdk.ResultFuture] = []
        self._started = False
        self._on_error = on_error

    def start(self) -> None:
        """Mark session as ready to accept writes."""
        self._started = True

    def write(self, text: str) -> None:
        """Queue a sentence for synthesis (sanitized for TTS)."""
        if not self._started:
            return
        clean = _sanitize_for_tts(text)
        if clean and not clean.isspace():
            future = self._synthesizer.speak_text_async(clean)
            self._futures.append(future)

    def close(self) -> None:
        """Signal that no more text will arrive (no-op — kept for interface compat)."""
        pass

    async def wait(self) -> None:
        """Wait for all queued audio to finish playing."""
        if not self._futures:
            return
        error_fired = False
        for future in self._futures:
            try:
                result = await asyncio.to_thread(future.get)
                if result.reason == speechsdk.ResultReason.Canceled and not error_fired:
                    details = result.cancellation_details
                    if details.reason == speechsdk.CancellationReason.Error:
                        print(f"[tts-stream] Synthesis error: {details.error_details}")
                        if self._on_error:
                            self._on_error()
                        error_fired = True
            except Exception as exc:
                if not error_fired:
                    print(f"[tts-stream] wait() error: {exc}", file=sys.stderr)
                    if self._on_error:
                        self._on_error()
                    error_fired = True

    def stop(self) -> None:
        """Immediately halt playback and clear the queue. Sync, any thread."""
        try:
            self._synthesizer.stop_speaking_async()
        except Exception:
            pass


class AzureTTS:
    """TTS using Azure Cognitive Services Speech SDK.

    Requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION env vars.
    """

    def __init__(
        self,
        speech_key: str,
        region: str,
        voice: str = "en-US-AvaMultilingualNeural",
    ):
        config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
        config.speech_synthesis_voice_name = voice
        self._config = config
        self.synthesizer = speechsdk.SpeechSynthesizer(speech_config=config)
        self._speaking = False

    def _reset_synthesizer(self) -> None:
        """Recreate the synthesizer to ensure clean state after errors."""
        try:
            self.synthesizer.stop_speaking_async()
        except Exception:
            pass
        self.synthesizer = speechsdk.SpeechSynthesizer(speech_config=self._config)

    def create_stream_session(self) -> StreamingTTSSession:
        """Create a new streaming TTS session backed by this synthesizer."""
        return StreamingTTSSession(
            self.synthesizer,
            on_error=self._reset_synthesizer,
        )

    async def speak(self, text: str) -> None:
        """Speak the given text aloud."""
        self._speaking = True
        try:
            await asyncio.to_thread(lambda: self._speak_internal(text))
        finally:
            self._speaking = False

    def _speak_internal(self, text: str):
        future = self.synthesizer.speak_text_async(_sanitize_for_tts(text))
        result = future.get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print("Speech synthesized for text [{}]".format(text))
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                print("Error details: {}".format(cancellation_details.error_details))
        return result

    def shutdown(self) -> None:
        """Force-stop TTS immediately. Sync, safe to call from any thread."""
        try:
            self.synthesizer.stop_speaking_async()
        except Exception:
            pass

    async def stop(self) -> None:
        """Stop TTS playback immediately."""
        if self._speaking:
            await asyncio.to_thread(
                lambda: self.synthesizer.stop_speaking_async().get()
            )
