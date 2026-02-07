# noaises-local — CLAUDE.md

## What This Is

Local-first, voice-first AI companion powered by the Claude Agent SDK. A desktop persona that listens, speaks, remembers, and evolves. See [`../Moonshot.md`](../Moonshot.md) for the full vision.

## Tech Stack

- **Python 3.10+**, managed with **uv** (`uv sync`, `uv run`)
- **Claude Agent SDK** (`claude-agent-sdk`) — agent loop, tool use, MCP, streaming, hooks
- **Hatchling** build backend, src-layout (`src/noaises/`)
- Entry point: `uv run noaises` (calls `noaises.main:main`)

## Project Structure

```
noaises-local/
├── src/noaises/
│   ├── __init__.py              # Package version
│   ├── main.py                  # Entry point — asyncio bootstrap
│   │
│   ├── agent/                   # Agent core
│   │   └── core.py              # ClaudeSDKClient wrapper, agent loop
│   │
│   ├── voice/                   # Voice pipeline
│   │   └── pipeline.py          # STT (Whisper) + TTS (system/ElevenLabs)
│   │
│   ├── memory/                  # Persistent memory
│   │   └── store.py             # Conversation history, preferences, context
│   │
│   ├── personality/             # Personality engine
│   │   └── engine.py            # Trait loading, system prompt injection, evolution
│   │
│   └── surface/                 # Desktop UI
│       └── desktop.py           # Always-on-top animated persona window
│
├── config/
│   └── personality.toml         # Personality configuration (name, tone, verbosity)
│
├── pyproject.toml               # Dependencies, build config, entry point
├── .python-version              # 3.10 (pinned by uv)
└── CLAUDE.md                    # This file
```

## Module Responsibilities

### `agent/core.py` — Agent Core
The beating heart. Wraps `ClaudeSDKClient` from the Claude Agent SDK into a REPL loop. Handles:
- Agent configuration (`ClaudeAgentOptions` — tools, permissions, model)
- Multi-turn conversation via `client.query()` + `client.receive_response()`
- Streaming response processing (`AssistantMessage` → `TextBlock`)

Current tools: Task, Bash, Glob, Grep, Read, Edit, Write, WebFetch, WebSearch. Permission mode: `acceptEdits`.

### `voice/pipeline.py` — Voice Pipeline (stub)
Wraps around the agent core — the SDK has no native voice support. Will handle:
- **STT**: OpenAI Whisper (local model or cloud API) — mic capture → text
- **TTS**: System TTS (`pyttsx3`) for low-latency, ElevenLabs for quality — text → speaker
- Audio device management, wake word detection

### `memory/store.py` — Persistent Memory (stub)
Local storage for everything that makes the companion *remember*. Will handle:
- Conversation history (session + cross-session)
- User preferences and facts learned over time
- Context retrieval for agent system prompt augmentation
- Storage backend: file-based or SQLite (TBD)

### `personality/engine.py` — Personality Engine (stub)
Makes LLL feel like a companion, not a tool. Will handle:
- Loading personality config from `config/personality.toml`
- Building and injecting personality traits into the system prompt
- Personality evolution — adapting tone/style based on interaction patterns
- Mood/energy state that shifts throughout the day

### `surface/desktop.py` — Desktop Surface (stub)
The visual presence. Will handle:
- Transparent always-on-top window (framework TBD: tkinter, PyQt, or Tauri)
- Animated persona with states: idle, listening, thinking, speaking
- Click/hover interactions, minimize/restore
- Visual feedback tied to voice pipeline state

## Architecture Flow

```
User speaks → [Voice In: Whisper STT] → text
  → [Personality Engine: augment prompt] → enriched prompt
  → [Agent Core: ClaudeSDKClient.query()] → Claude API
  → [Agent Core: receive_response()] → response text
  → [Personality Engine: style response] → styled text
  → [Voice Out: TTS] → audio → User hears
  → [Memory Store: persist exchange]
  → [Surface: update animation state]
```

## Implementation Scope

### Phase 1 — Text REPL (current)
- [x] Project scaffold with uv
- [x] Agent core with ClaudeSDKClient REPL loop
- [ ] Personality engine loading `config/personality.toml` into system prompt
- [ ] Memory store persisting conversation history locally
- [ ] Hook into agent for memory-augmented context

### Phase 2 — Voice
- [ ] Whisper STT integration (local model)
- [ ] System TTS (`pyttsx3`) integration
- [ ] Voice pipeline wiring: mic → STT → agent → TTS → speaker
- [ ] ElevenLabs TTS as optional high-quality backend

### Phase 3 — Desktop Surface
- [ ] Always-on-top transparent window
- [ ] Animated persona (idle, listening, thinking, speaking)
- [ ] Surface ↔ voice pipeline state sync

### Phase 4 — Intelligence
- [ ] Personality evolution over time
- [ ] Proactive interactions (time-based, context-based)
- [ ] Custom MCP tools for system integration
- [ ] Wake word detection for hands-free activation

## Development Commands

```bash
uv sync              # Install/update dependencies
uv run noaises       # Run the companion (text REPL mode)
uv add <package>     # Add a dependency
uv run python -m pytest  # Run tests (when we have them)
```

## Environment

- `ANTHROPIC_API_KEY` — Required. The Claude API key for inference.
- Future: `ELEVENLABS_API_KEY` for high-quality TTS.

## Conventions

- **Async-first**: The agent loop is async. New modules that interact with the agent should be async.
- **No over-engineering**: Build what's needed now. Stubs exist for future modules — fill them in when the time comes.
- **Local data only**: No external storage. Everything persists on the user's machine.
- **src-layout**: All source lives under `src/noaises/`. Imports use `from noaises.x.y import z`.
