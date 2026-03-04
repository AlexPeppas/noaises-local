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

from noaises.agent.core import (
    query_agent_interruptible,
    query_stream_agent_interruptible,
)
from noaises.interrupt.controller import InterruptController
from noaises.memory.distiller import distill_memories, should_distill
from noaises.personality.distiller import distill_personality
from noaises.memory.store import MemoryStore
from noaises.memory.tools import (
    MEMORY_META_PROMPT,
    MEMORY_TOOL_NAMES,
    create_memory_mcp_server,
)
from noaises.personality.engine import PersonalityEngine
from noaises.sessions.engine import SessionEngine
from noaises.tools.camera_tool import (
    CAMERA_META_PROMPT,
    CAMERA_TOOL_NAMES,
    create_camera_mcp_server,
)
from noaises.tools.screen_capture import CaptureScreenTool
from noaises.vision.pipeline import VisionPipeline
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
    speech_voice = os.environ.get("AZURE_SPEECH_VOICE")
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
    vision_pipeline = VisionPipeline(
        settings.camera_device_index,
        settings.camera_frame_interval,
        settings.vision_model_name,
    )

    # Optionally pre-load vision model so camera_on is instant
    if settings.vision_preload:
        print("[vision] Pre-loading vision model...")
        await asyncio.to_thread(vision_pipeline._model.load)
        print("[vision] Vision model ready.")
    else:
        print("[vision] Vision model will load on first camera use (~80s).")

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

            # -- Vision: flush buffered frames if camera is active --
            vision_context = ""
            if vision_pipeline.is_active:
                frame_count = vision_pipeline.pending_frame_count
                if frame_count > 0:
                    print(f"[vision] Processing {frame_count} frames...")
                    if surface:
                        surface.set_state("seeing")
                description = await vision_pipeline.flush_and_describe()
                if description:
                    print(f"[vision] Done: {description[:150]}[TRUNCATED]")
                    vision_context = (
                        f"\n\n[Visual observation of the user: {description}]"
                    )

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

            # Rebuild MCP servers each turn
            memory_server = create_memory_mcp_server(full_memory)
            camera_server = create_camera_mcp_server(vision_pipeline)
            mcp_servers = {"memory": memory_server, "camera": camera_server}

            # Build system prompt with memory state + guidance
            memory_state = memory_store.build_memory_state(full_memory)
            session_summary = session.get_today_summary()
            system_prompt = personality.build_system_prompt(
                memory_state,
                session_summary,
                memory_guidance=MEMORY_META_PROMPT + "\n" + CAMERA_META_PROMPT,
            )

            if settings.enable_streaming:
                # ── Streaming path (token-by-token) ──
                agent_stream = query_stream_agent_interruptible(
                    user_input + vision_context + screenshot_context,
                    system_prompt,
                    interrupt,
                    mcp_servers=mcp_servers,
                    extra_allowed_tools=MEMORY_TOOL_NAMES + CAMERA_TOOL_NAMES,
                )

                if voice:
                    response, was_interrupted = await voice.speak_streaming(
                        agent_stream,
                        interrupt,
                        surface=surface,
                        personality_name=personality.name,
                    )
                else:
                    response = ""
                    was_interrupted = False
                    first_token = True
                    in_thinking = False
                    async for event in agent_stream:
                        if event.kind == "thinking_delta":
                            if not in_thinking:
                                in_thinking = True
                                print("\n  [thinking] ", end="", flush=True)
                            print(event.thinking, end="", flush=True)
                        elif event.kind == "text_delta":
                            if in_thinking:
                                in_thinking = False
                                print()  # end thinking line
                            if first_token:
                                first_token = False
                                print(
                                    f"\n{personality.name}: ",
                                    end="",
                                    flush=True,
                                )
                            print(event.text, end="", flush=True)
                        elif event.kind == "tool_use":
                            if surface:
                                if event.tool_name == "WebSearch":
                                    state = "searching"
                                elif event.tool_name in (
                                    "mcp__camera__camera_on",
                                    "mcp__camera__camera_off",
                                ):
                                    state = "seeing"
                                elif event.tool_name in (
                                    "mcp__memory__memory_store",
                                    "mcp__memory__memory_remove",
                                ):
                                    state = "remembering"
                                else:
                                    state = "thinking"
                                surface.set_state(state)
                        elif event.kind == "tool_result":
                            if surface and not first_token:
                                surface.set_state("speaking")
                        elif event.kind == "done":
                            response = event.full_response
                            was_interrupted = event.was_interrupted
                            break
                    print()  # newline after typewriter output
            else:
                # ── Non-streaming path (full response at once) ──
                response, was_interrupted = await query_agent_interruptible(
                    user_input + vision_context + screenshot_context,
                    system_prompt,
                    interrupt,
                    mcp_servers=mcp_servers,
                    extra_allowed_tools=MEMORY_TOOL_NAMES + CAMERA_TOOL_NAMES,
                    surface=surface,
                )
                if not was_interrupted:
                    print(f"\n{personality.name}: {response}\n")

            interrupt.disable()

            # Save memory after each turn (agent may have called memory tools)
            memory_store.save_all(full_memory)

            if was_interrupted:
                if response:
                    session.append("assistant", response)
                    session.append(
                        "system",
                        "[User interrupted before full response was heard]",
                    )
                if surface:
                    surface.set_state("idle")
                continue

            # ── Speaking (non-streaming voice path) ──
            if not settings.enable_streaming and voice:
                if surface:
                    surface.set_state("speaking")
                interrupt.enable()
                await voice.speak_interruptible(response, interrupt)
                if interrupt.is_interrupted:
                    session.append(
                        "system",
                        "[User interrupted before full response was heard]",
                    )
                interrupt.disable()

            # ── Post-response bookkeeping ──
            session.append("assistant", response)
            personality.record_interaction()

            if surface:
                surface.set_state("idle")

            # Distill every N turns (fire-and-forget)
            if should_distill(turn_count):
                asyncio.create_task(
                    distill_memories(full_memory, session, memory_store)
                )
                asyncio.create_task(
                    distill_personality(personality, full_memory, session, memory_store)
                )

    except (KeyboardInterrupt, EOFError):
        print(f"\n{personality.name} is going to sleep. Goodbye!")
    except Exception as e:
        import traceback

        print(f"\n[error] Unexpected error: {e}")
        traceback.print_exc()
    finally:
        # Stop all blocking voice operations so threads can exit
        if voice:
            voice.shutdown()
        vision_pipeline.shutdown()

        # Save memory on exit
        memory_store.save_all(full_memory)

        # Play sleep animation, then close
        if surface:
            surface.set_state("sleeping")
            try:
                await asyncio.sleep(3)  # let the zzz animation play
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass  # second Ctrl+C — skip animation
            surface.destroy()

        # Force exit to kill any lingering thread-pool threads
        # (sounddevice stream.read, input(), etc. that can't be interrupted)
        os._exit(0)


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
