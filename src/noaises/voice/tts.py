"""Text-to-speech providers."""

from __future__ import annotations

import asyncio
from typing import Protocol
import azure.cognitiveservices.speech as speechsdk

class TTSProvider(Protocol):
    """Protocol for text-to-speech providers."""

    async def speak(self, text: str) -> None: ...

    async def stop(self) -> None: ...


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
        self.synthesizer = speechsdk.SpeechSynthesizer(speech_config=config)
        self._speaking = False

    async def speak(self, text: str) -> None:
        """Speak the given text aloud."""
        self._speaking = True
        try:
            await asyncio.to_thread(
                lambda: self._speak_internal(text)
            )
        finally:
            self._speaking = False

    def _speak_internal(self, text: str):
        future = self.synthesizer.speak_text_async(text)
        result = future.get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print("Speech synthesized for text [{}]".format(text))
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                print("Error details: {}".format(cancellation_details.error_details))
        result.get
        return result
    
    async def stop(self) -> None:
        """Stop TTS playback immediately."""
        if self._speaking:
            await asyncio.to_thread(
                lambda: self.synthesizer.stop_speaking_async().get()
            )
