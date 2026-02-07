"""Text-to-speech providers."""

from __future__ import annotations

import asyncio
from typing import Protocol


class TTSProvider(Protocol):
    """Protocol for text-to-speech providers."""

    async def speak(self, text: str) -> None: ...


class AzureTTS:
    """TTS using Azure Cognitive Services Speech SDK.

    Requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION env vars.
    """

    def __init__(
        self,
        speech_key: str,
        region: str,
        voice: str = "en-US-JennyNeural",
    ):
        import azure.cognitiveservices.speech as speechsdk

        config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
        config.speech_synthesis_voice_name = voice
        self.synthesizer = speechsdk.SpeechSynthesizer(speech_config=config)

    async def speak(self, text: str) -> None:
        """Speak the given text aloud."""
        await asyncio.to_thread(
            lambda: self.synthesizer.speak_text_async(text).get()
        )
