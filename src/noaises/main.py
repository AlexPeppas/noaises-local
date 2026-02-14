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

from noaises.agent.core import query_agent_interruptible
from noaises.interrupt.controller import InterruptController
from noaises.memory.distiller import distill_memories, should_distill
from noaises.memory.store import MemoryStore
from noaises.memory.tools import (
    MEMORY_META_PROMPT,
    MEMORY_TOOL_NAMES,
    create_memory_mcp_server,
)
from noaises.personality.engine import PersonalityEngine
from noaises.sessions.engine import SessionEngine
from noaises.tools.screen_capture import CaptureScreenTool
from .config import settings

# Repo stuff
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # noaises-local/
CONFIG_DIR = BASE_DIR / "config"
SURFACE_DIR = Path(__file__).resolve().parent / "surface" / "web"

# Home dir stuff
HOME_DIR = settings.noaises_home_resolved  # ~/.noaises
MEMORY_DIR = HOME_DIR / "memory"
SESSIONS_DIR = HOME_DIR / "sessions"
PERSONALITY_DIR = HOME_DIR / "personality"
ARTIFACTS_DIR = HOME_DIR / "artifacts"


def _init_voice():
    """Try to initialize the voice pipeline. Returns VoicePipeline or None."""
    speech_key = os.environ.get("AZURE_SPEECH_KEY")
    speech_region = os.environ.get("AZURE_SPEECH_REGION")

    try:
        from noaises.voice.stt import WhisperSTT
        from noaises.voice.tts import AzureTTS
        from noaises.voice.pipeline import VoicePipeline

        if not speech_key or not speech_region:
            print(
                "[voice] AZURE_SPEECH_KEY / AZURE_SPEECH_REGION not set — TTS disabled."
            )
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
    loop = asyncio.get_running_loop()
    interrupt = InterruptController(loop)

    # Initialize core modules
    memory_store = MemoryStore(MEMORY_DIR)
    full_memory = memory_store.load_full_memory()
    session = SessionEngine(SESSIONS_DIR)
    personality = PersonalityEngine(CONFIG_DIR / "personality.toml", PERSONALITY_DIR)
    screen_capture = CaptureScreenTool(ARTIFACTS_DIR / "screenshots")

    # Initialize optional voice
    voice = _init_voice()

    turn_count = 0

    mode = "voice" if voice else "text"
    print(
        f"{personality.name} is awake ({mode} mode). {'Speak' if voice else 'Type a message'} (Ctrl+C to quit).\n"
    )

    try:
        while True:
            # ── Listening (not interruptible) ──
            interrupt.disable()
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
            session.append("user", user_input)

            # -- Screen capture (if user asks about their screen) --
            screenshot_context = ""
            if CaptureScreenTool.detect_intent(user_input):
                if surface:
                    surface.set_state("searching")
                screenshot_path = await asyncio.to_thread(
                    screen_capture.capture, surface
                )
                screenshot_context = (
                    f"\n\n[A screenshot of the user's current screen has been saved. "
                    f"Use the Read tool to view it at: {screenshot_path}]"
                )

            # ── Thinking (interruptible via poll) ──
            interrupt.enable()
            if surface:
                surface.set_state("thinking")

            turn_count += 1

            # Rebuild MCP server each turn (binds to current memory state)
            memory_server = create_memory_mcp_server(full_memory)
            mcp_servers = {"memory": memory_server}

            # Build system prompt with memory state + guidance
            memory_state = memory_store.build_memory_state(full_memory)
            session_summary = session.get_today_summary()
            system_prompt = personality.build_system_prompt(
                memory_state, session_summary, memory_guidance=MEMORY_META_PROMPT
            )

            response, was_interrupted = await query_agent_interruptible(
                user_input + screenshot_context,
                system_prompt,
                interrupt,
                mcp_servers=mcp_servers,
                extra_allowed_tools=MEMORY_TOOL_NAMES,
                surface= surface)
            
            interrupt.disable()

            # Save memory after each turn (agent may have called memory tools)
            memory_store.save_all(full_memory)

            if was_interrupted:
                if response:
                    session.append("assistant", response)
                if surface:
                    surface.set_state("idle")
                continue

            # ── Speaking (interruptible via barge-in + click) ──
            session.append("assistant", response)
            personality.record_interaction()

            if surface:
                surface.set_state("speaking")

            print(f"\n{personality.name}: {response}\n")

            if voice:
                interrupt.enable()
                await voice.speak_interruptible(response, interrupt)
                was_interrupted = interrupt.is_interrupted
                interrupt.disable()

                if was_interrupted:
                    session.append(
                        "system",
                        "[User interrupted before full response was heard]",
                    )

            if surface:
                surface.set_state("idle")

            # Distill every N turns (fire-and-forget)
            if should_distill(turn_count):
                asyncio.create_task(
                    distill_memories(full_memory, session, memory_store)
                )

    except (KeyboardInterrupt, EOFError):
        print(f"\n{personality.name} is going to sleep. Goodbye!")
    except Exception as e:
        import traceback

        print(f"\n[error] Unexpected error: {e}")
        traceback.print_exc()
    finally:
        # Save memory on exit
        memory_store.save_all(full_memory)
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
