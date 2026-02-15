# noaises-local — CLAUDE.md

## What This Is

A local-first, voice-first AI companion powered by the Claude Agent SDK. An animated desktop persona that listens, speaks, remembers, and evolves. See [`README.md`](README.md) for full architecture docs.

**Guiding principles**: All interaction is voice-first — you speak, it listens, it responds aloud. No keyboard required for day-to-day use. It has persistent personality that evolves across sessions, remembers preferences, recalls past conversations. Everything runs locally — conversations, memories, personality state stay on your machine. The only external call is to the LLM API for inference.

## Tech Stack

- **Python 3.11+**, managed with **uv** (`uv sync`, `uv run`)
- **Claude Agent SDK** (`claude-agent-sdk`) — agent loop, tool use, MCP, streaming
- **Hatchling** build backend, src-layout (`src/noaises/`)
- Entry point: `uv run noaises` (calls `noaises.main:main`)

## Project Structure

```
src/noaises/
├── main.py                      # Orchestrator — turn loop, wiring, shutdown
├── config.py                    # Pydantic settings (streaming, distill, paths)
├── logger.py                    # Structured JSON logging
│
├── agent/core.py                # ClaudeSDKClient wrapper — streaming + batch
│
├── voice/
│   ├── stt.py                   # WhisperSTT (faster-whisper, local)
│   ├── tts.py                   # AzureTTS + StreamingTTSSession
│   └── pipeline.py              # VAD, barge-in, sentence buffer, speak_streaming
│
├── memory/
│   ├── model.py                 # Pydantic models (ShortTerm, LongTerm, FullMemoryContext)
│   ├── store.py                 # Markdown persistence (short_term/*.md, long_term.md)
│   ├── distiller.py             # Background consolidation via Haiku
│   └── tools.py                 # MCP server (memory_store, memory_remove)
│
├── personality/engine.py        # TOML config + evolution + system prompt building
├── sessions/engine.py           # Daily JSONL conversation logs
├── interrupt/controller.py      # Thread-safe interrupt signaling
│
├── surface/
│   ├── desktop.py               # pywebview wrapper (frameless, transparent, on-top)
│   └── web/                     # HTML/CSS/JS persona animations (6 states)
│
└── tools/screen_capture.py      # Screen capture + intent detection
```

## Module Responsibilities

### `agent/core.py` — Agent Core
Wraps `ClaudeSDKClient` with two query modes controlled by `settings.enable_streaming`:
- **`query_agent_interruptible()`** — Batch: full response at once, poll-based interrupt
- **`query_stream_agent_interruptible()`** — Streaming: async generator yielding `AgentStreamEvent` per token (`thinking_delta`, `text_delta`, `tool_use`, `tool_result`, `done`)

Uses `include_partial_messages=True` on the SDK to receive `StreamEvent` with raw Anthropic API events (`content_block_delta` → `text_delta` / `thinking_delta`).

Tools: Task, Bash, Glob, Grep, Read, Edit, Write, WebFetch, WebSearch + MCP memory tools. Model: `claude-opus-4-5`, fallback `claude-sonnet-4-5`. Permission mode: `acceptEdits`.

### `voice/` — Voice Pipeline
- **`stt.py`**: Local Whisper via faster-whisper. Mic → audio → text.
- **`tts.py`**: Azure Speech SDK with V2 WebSocket endpoint. `AzureTTS` for batch, `StreamingTTSSession` for text-stream synthesis (`SpeechSynthesisRequest(TextStream)` — write sentences incrementally, audio plays before all text arrives).
- **`pipeline.py`**: `VoicePipeline` — audio capture with energy-based VAD, `speak_interruptible()` for batch TTS, `speak_streaming()` for streaming TTS. `SentenceBuffer` accumulates tokens and flushes at `.!?:;\n` boundaries. Barge-in detection via secondary mic stream (5x silence threshold, 3 consecutive chunks).

### `memory/` — Persistent Memory
- **`model.py`**: Pydantic models — `ShortTermMemory`, `LongTermMemory`, `FullMemoryContext`
- **`store.py`**: Markdown files — `long_term.md` + `short_term/YYYY-MM-DD.md`. `## Category` headers, `- item` bullets. Categories are dynamic.
- **`distiller.py`**: Every N turns, sends session history to Haiku → extracts `{tier, category, content, action}` → writes to memory. Fire-and-forget.
- **`tools.py`**: MCP server exposing `memory_store` / `memory_remove`. Agent actively manages its own memory.

### `personality/engine.py` — Personality Engine
Loads `config/personality.toml` (name, tone, verbosity, traits). Builds system prompt per turn: base identity + evolution traits + memory context + session summary + MCP guidance. Tracks evolution in `personality_evolution.json`.

### `sessions/engine.py` — Session Logging
Append-only JSONL per day. Entries: `{sender, text, ts}`. Feeds distiller and system prompt summary.

### `surface/` — Desktop Surface
pywebview + WebView2: 250x320px frameless, transparent, always-on-top. Six states: idle, listening, thinking, searching, speaking, sleeping. JS state machine with Lottie blob + particle effects.

### `interrupt/controller.py` — Interrupt Controller
Thread-safe bridge: `threading.Event` (for blocking code poll) + `asyncio.Event` (for coroutine await). `fire()` callable from any thread.

## Architecture Flow

```
Streaming path (enable_streaming=True):
  User input → system prompt build → query_stream_agent_interruptible()
    → thinking_delta tokens → console [thinking] (not spoken)
    → text_delta tokens → console typewriter + SentenceBuffer → StreamingTTSSession
    → tool_use/tool_result → surface state updates
    → done → session log + memory save + distill

Batch path (enable_streaming=False):
  User input → system prompt build → query_agent_interruptible()
    → full response → print → speak_interruptible() → session log + memory save
```

## Threading Model

- **Main thread**: pywebview event loop (Windows GUI requirement)
- **Background thread**: asyncio loop (agent, voice, memory, distillation)
- **to_thread**: sounddevice capture, TTS blocking calls
- **InterruptController**: bridges threads via dual Event pattern

## Data Layout (`~/.noaises/`)

```
memory/long_term.md              # Permanent facts
memory/short_term/YYYY-MM-DD.md  # Daily observations
sessions/YYYY-MM-DD.jsonl        # Conversation logs
personality/personality_evolution.json
artifacts/screenshots/            # Auto-cleaned after 1h
```

## Configuration (`config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `NOAISES_HOME` | `~/.noaises` | Data directory |
| `enable_streaming` | `True` | Token-by-token output + streaming TTS |
| `memory_distill_enabled` | `True` | Background memory consolidation |
| `memory_distill_interval` | `5` | Distill every N turns |
| `memory_distill_model` | `claude-haiku-4-5-20251001` | Distillation model |

## Environment

- `ANTHROPIC_API_KEY` — Required. Claude API key.
- `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` — Required for voice mode. Azure TTS.
- `AZURE_SPEECH_VOICE` — Optional. Default `en-US-AvaMultilingualNeural`.

## Development Commands

```bash
uv sync              # Install/update dependencies
uv run noaises       # Run the companion
uv add <package>     # Add a dependency
```

## Conventions

- **Async-first**: Agent loop is async. New modules interacting with the agent must be async.
- **No over-engineering**: Build what's needed now. Don't abstract for hypothetical futures.
- **Local data only**: No external storage. Everything persists on the user's machine.
- **src-layout**: All source under `src/noaises/`. Imports: `from noaises.x.y import z`.
- **Graceful degradation**: No voice keys → text mode. No pywebview → headless. Every layer optional except agent core.
