"""Text-to-speech providers."""

from __future__ import annotations

import asyncio
import re
from typing import Protocol

import azure.cognitiveservices.speech as speechsdk


# Regex patterns for sanitizing text before TTS ingestion.
# Azure's streaming input_stream.write() chokes on emoji and markdown
# that the batch speak_text_async() handles internally.
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
    return text.strip()



class TTSProvider(Protocol):
    """Protocol for text-to-speech providers."""

    async def speak(self, text: str) -> None: ...

    async def stop(self) -> None: ...


class StreamingTTSSession:
    """A single streaming TTS session using Azure's text-stream synthesis.

    Text is fed incrementally via ``write()``; audio starts playing before
    all text has arrived. Call ``close()`` to signal end-of-text, then
    ``wait()`` to block until all audio has finished playing.
    """

    def __init__(
        self,
        synthesizer: speechsdk.SpeechSynthesizer,
    ):
        self._synthesizer = synthesizer
        self._request = speechsdk.SpeechSynthesisRequest(
            input_type=speechsdk.SpeechSynthesisRequestInputType.TextStream,
        )
        self._future: speechsdk.ResultFuture | None = None

    def start(self) -> None:
        """Begin synthesis — audio will start as text is written."""
        self._future = self._synthesizer.speak_async(self._request)

    def write(self, text: str) -> None:
        """Feed a chunk of text into the stream (sanitized for TTS)."""
        clean = _sanitize_for_tts(text)
        if clean:
            self._request.input_stream.write(clean)

    def close(self) -> None:
        """Signal that no more text will arrive."""
        try:
            self._request.input_stream.close()
        except Exception:
            pass

    async def wait(self) -> None:
        """Wait for all audio to finish playing (runs blocking .get() in thread)."""
        if self._future is not None:
            result = await asyncio.to_thread(self._future.get)
            if result.reason == speechsdk.ResultReason.Canceled:
                details = result.cancellation_details
                if details.reason == speechsdk.CancellationReason.Error:
                    print(f"[tts-stream] Synthesis error: {details.error_details}")

    def stop(self) -> None:
        """Immediately halt playback and close the stream. Sync, any thread."""
        try:
            self._request.input_stream.close()
        except Exception:
            pass
        try:
            self._synthesizer.stop_speaking_async()
        except Exception:
            pass


class AzureTTS:
    """TTS using Azure Cognitive Services Speech SDK.

    Requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION env vars.
    Uses the V2 WebSocket endpoint for streaming text input support.
    """

    def __init__(
        self,
        speech_key: str,
        region: str,
        voice: str = "en-US-AvaMultilingualNeural",
    ):
        config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
        config.speech_synthesis_voice_name = voice
        # V2 WebSocket endpoint — required for SpeechSynthesisRequest(TextStream)
        config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_Endpoint,
            f"wss://{region}.tts.speech.microsoft.com/cognitiveservices/websocket/v2",
        )
        self._config = config
        self.synthesizer = speechsdk.SpeechSynthesizer(speech_config=config)
        self._speaking = False

    def create_stream_session(self) -> StreamingTTSSession:
        """Create a new streaming TTS session backed by this synthesizer."""
        return StreamingTTSSession(self.synthesizer)

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
