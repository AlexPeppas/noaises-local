"""Main entry point — orchestrates memory, personality, agent, voice, and surface.

Threading model:
- Main thread -> pywebview (GUI requires it on Windows)
- Background thread -> asyncio event loop (agent, memory, voice)
If no surface is available, asyncio runs on the main thread as normal.

Shutdown flow:
- Ctrl+C in console -> async loop exits -> surface.destroy() kills webview -> process exits
- User closes webview window -> on_closed fires -> os._exit() kills everything
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

from noaises.agent.core import query_agent
from noaises.memory.store import MemoryStore
from noaises.personality.engine import PersonalityEngine

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # noaises-local/
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
SURFACE_DIR = Path(__file__).resolve().parent / "surface" / "web"


def _init_voice():
    """Try to initialize the voice pipeline. Returns VoicePipeline or None."""
    speech_key = os.environ.get("AZURE_SPEECH_KEY")
    speech_region = os.environ.get("AZURE_SPEECH_REGION")

    try:
        from noaises.voice.stt import WhisperSTT
        from noaises.voice.tts import AzureTTS
        from noaises.voice.pipeline import VoicePipeline

        if not speech_key or not speech_region:
            print("[voice] AZURE_SPEECH_KEY / AZURE_SPEECH_REGION not set — TTS disabled.")
            return None

        stt = WhisperSTT(model_size="base")
        tts = AzureTTS(speech_key=speech_key, region=speech_region)
        print("[voice] Voice pipeline initialized (Whisper STT + Azure TTS).")
        return VoicePipeline(stt=stt, tts=tts)
    except ImportError as e:
        print(f"[voice] Voice dependencies not installed ({e}) — text mode only.")
        return None


def _init_surface():
    """Try to create the desktop surface. Returns DesktopSurface or None."""
    try:
        from noaises.surface.desktop import DesktopSurface
        return DesktopSurface(SURFACE_DIR)
    except ImportError as e:
        print(f"[surface] pywebview not installed ({e}) — headless mode.")
        return None


async def async_main(surface=None):
    """Run the companion loop. Called from the asyncio event loop."""
    # Initialize core modules
    memory = MemoryStore(DATA_DIR)
    personality = PersonalityEngine(CONFIG_DIR / "personality.toml", DATA_DIR)

    # Initialize optional voice
    voice = _init_voice()

    # Start consolidation background task
    consolidation_task = asyncio.create_task(memory.consolidation_loop())

    mode = "voice" if voice else "text"
    print(f"{personality.name} is awake ({mode} mode). {'Speak' if voice else 'Type a message'} (Ctrl+C to quit).\n")

    try:
        while True:
            # -- Input --
            if surface:
                surface.set_state("listening")

            if voice:
                user_input = await voice.listen()
                if not user_input:
                    continue
                print(f"You: {user_input}")
            else:
                user_input = await asyncio.to_thread(input, "You: ")
                if not user_input.strip():
                    continue

            # Store user message
            memory.append_short_term("user", user_input)

            # -- Process --
            if surface:
                surface.set_state("thinking")

            long_term = memory.get_long_term_summary()
            short_term = memory.get_short_term_today_summary()
            system_prompt = personality.build_system_prompt(long_term, short_term)

            response = await query_agent(user_input, system_prompt)

            # -- Output --
            memory.append_short_term("assistant", response)
            personality.record_interaction()

            if surface:
                surface.set_state("speaking")

            if voice:
                print(f"\n{personality.name}: {response}\n")
                await voice.speak(response)
            else:
                print(f"\n{personality.name}: {response}\n")

            if surface:
                surface.set_state("idle")

    except (KeyboardInterrupt, EOFError):
        print(f"\n{personality.name} is going to sleep. Goodbye!")
    finally:
        consolidation_task.cancel()
        # Play sleep animation, then close
        if surface:
            surface.set_state("sleeping")
            await asyncio.sleep(3)  # let the zzz animation play
            surface.destroy()


def _run_async_loop(surface):
    """Entry for the background thread — creates and runs the asyncio loop."""
    asyncio.run(async_main(surface))


def main():
    load_dotenv(BASE_DIR / ".env")

    surface = _init_surface()

    if surface:
        # Async loop in background thread, webview on main thread
        loop_thread = threading.Thread(
            target=_run_async_loop, args=(surface,), daemon=True
        )
        loop_thread.start()
        print("[surface] Desktop persona launched.")

        def _on_window_closed():
            # Window closed by user — force exit the whole process.
            # The daemon thread will die automatically.
            print("\nnoaises is going to sleep. Goodbye!")
            os._exit(0)

        surface.run_blocking(on_closed=_on_window_closed)  # blocks main thread
    else:
        # No surface — asyncio gets the main thread
        asyncio.run(async_main())


if __name__ == "__main__":
    main()
