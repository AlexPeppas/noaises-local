# noaises — Local AI Companion

A local-first, voice-first AI companion that lives on your desktop. It listens, speaks, remembers, and evolves — powered by the Claude Agent SDK.

> **Not a chatbot.** A companion with personality, memory, and presence.

---

## Quick Start

```bash
uv sync                # install dependencies
uv run noaises         # launch the companion
```

Set these environment variables before running:

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API access |
| `AZURE_SPEECH_KEY` | For voice | Azure TTS |
| `AZURE_SPEECH_REGION` | For voice | Azure TTS region |

Without voice env vars, noaises runs in **text mode** (keyboard input, typewriter output). With them, it runs in **voice mode** (speak and hear back).

---

## Architecture

The system is built as **five independent layers** that compose through a central orchestrator. Each layer owns exactly one concern and can be swapped, disabled, or evolved independently.

```
┌─────────────────────────────────────────────────────────────┐
│                     main.py (Orchestrator)                   │
│                                                             │
│   Wires layers together · Runs the turn loop · Handles     │
│   shutdown · Decides streaming vs non-streaming path        │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  Voice   │  Agent   │ Memory   │Personality│    Surface     │
│ Pipeline │  Core    │  Store   │  Engine   │   (Desktop)    │
│          │          │          │           │                │
│ STT/TTS  │ Claude   │ Short +  │ Traits +  │ Animated       │
│ Barge-in │ SDK      │ Long     │ Evolution │ Persona        │
│ VAD      │ Tools    │ term     │ Tone      │ Window         │
│ Streaming│ MCP      │ Distill  │ Mood      │ 6 states       │
└──────────┴──────────┴──────────┴──────────┴─────────────────┘
```

### Why Layers?

Each layer degrades gracefully. No voice keys? Text mode. No pywebview? Headless. Memory corrupt? Fresh start. This isn't defensive coding — it's the architecture. Every layer is optional except the agent core.

---

## The Turn Loop

A single interaction flows through the system like this:

```
                    ┌─────────────┐
                    │  User Input │
                    │ (mic / kbd) │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   Voice In  │  Whisper STT (local model)
                    │  or text    │  Energy-based VAD → silence detection
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │    System Prompt Build  │
              │                         │
              │  personality.toml       │
              │  + evolution traits     │
              │  + long-term memory     │
              │  + short-term memory    │
              │  + session summary      │
              │  + memory MCP guidance  │
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │ Agent Core  │  Claude SDK → claude-opus-4-5
                    │             │  Tools: Bash, Read, Write, WebSearch...
                    │  streaming  │  MCP: memory_store, memory_remove
                    │  or batch   │
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │    Response Output      │
              │                         │
              │  Streaming: tokens →    │
              │    sentence buffer →    │
              │    TTS stream + print   │
              │                         │
              │  Batch: full text →     │
              │    print → speak        │
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │  Post-Turn  │  Save session · Save memory
                    │             │  Distill (every N turns)
                    └─────────────┘
```

---

## Layer Deep Dives

### 1. Voice Pipeline (`voice/`)

Three components that handle everything between the user's mouth and their ears.

| Component | File | What It Does |
|---|---|---|
| **STT** | `stt.py` | Local Whisper model (faster-whisper). Mic → audio → text. |
| **TTS** | `tts.py` | Azure Speech SDK. Text → audio → speaker. Supports streaming. |
| **Pipeline** | `pipeline.py` | Glues STT + TTS. VAD, barge-in detection, sentence buffering. |

**Streaming TTS** is the key latency win. Instead of waiting for the full response:

```
Traditional:  [wait 3-5s for full response] ──────────── [speak all at once]
Streaming:    [~1s] [speak sentence 1] [speak sentence 2] [speak sentence 3]...
```

Tokens arrive individually, get accumulated in a `SentenceBuffer` until a sentence boundary (`.!?:;\n`), then each complete sentence is flushed to Azure's WebSocket v2 text-stream endpoint. Audio starts playing within ~1-2 seconds of the first token.

**Barge-in** lets the user interrupt by speaking. A secondary mic stream monitors RMS energy during TTS playback. If sustained loud audio is detected (3 consecutive chunks above 5x the silence threshold), TTS is killed and the turn ends.

### 2. Agent Core (`agent/core.py`)

Wraps the Claude Agent SDK into two query modes:

- **`query_agent_interruptible()`** — Sends a query, collects the full response, returns it. Simple, reliable.
- **`query_stream_agent_interruptible()`** — Async generator that yields `AgentStreamEvent` objects token by token. Enables streaming TTS and typewriter console output.

The mode is selected by `settings.enable_streaming` (default: `True`).

Stream events:

| Event | When | Used For |
|---|---|---|
| `thinking_delta` | Extended thinking token | Console display (not spoken) |
| `text_delta` | Response token | Console print + TTS feed |
| `tool_use` | Agent invokes a tool | Surface state update |
| `tool_result` | Tool returns | Surface state update |
| `done` | Stream complete | Full response for logging |

### 3. Memory (`memory/`)

Two-tier local storage. No cloud. Everything stays on your machine.

```
~/.noaises/memory/
├── long_term.md              # Persistent facts, preferences, context
└── short_term/
    ├── 2026-02-14.md         # Yesterday's observations
    └── 2026-02-15.md         # Today's observations
```

Both tiers use the same Markdown format — `## Category` headers with `- item` bullet lists. Categories are dynamic (the agent decides what to name them based on what it learns).

**Memory MCP Tools** — The agent has two MCP tools (`memory_store`, `memory_remove`) that let it actively manage its own memory during conversation. When you mention your name, your preferences, or correct something — it writes that to memory itself.

**Distillation** — Every N turns (default: 5), a background task sends recent session history to a fast model (Haiku) which extracts structured facts and writes them to memory. Fire-and-forget — never blocks the conversation.

```
Session JSONL ──► Haiku distiller ──► {tier, category, content, action}
                                            │
                                    ┌───────┴───────┐
                                    ▼               ▼
                              short_term.md    long_term.md
```

### 4. Personality (`personality/engine.py`)

Loaded from `config/personality.toml`:

```toml
[personality]
name = "noaises"
tone = "friendly, curious, playful"
verbosity = "concise"

[personality.traits]
humor = "witty, light sarcasm"
curiosity = "asks follow-up questions"
empathy = "notices user mood"
```

The engine builds a system prompt per turn by compositing:

1. **Base identity** — name, tone, verbosity, traits from TOML
2. **Evolution** — tone adjustments and learned behaviors tracked in `personality_evolution.json`
3. **Memory context** — formatted long-term + short-term memory
4. **Session summary** — last 20 turns of conversation
5. **Tool guidance** — how to use memory MCP tools

The personality isn't static — it accumulates learned traits and tone shifts over time.

### 5. Surface (`surface/`)

A 250x320px frameless, always-on-top, transparent window powered by pywebview + WebView2.

Six animation states driven by a JS state machine:

| State | Visual | Trigger |
|---|---|---|
| **idle** | Gentle jelly bob | Default / after response |
| **listening** | Teal glow ring + pulse | Mic active |
| **thinking** | Warm glow + wobble + thought dots | Waiting for Claude |
| **searching** | Blue glow + scan + particle emojis | Tool use (WebSearch) |
| **speaking** | Energetic bounce + color boost | TTS playing |
| **sleeping** | Dim + slow breathe + floating zzz | Shutdown |

The surface is the visual heartbeat — it reflects what the system is doing at any moment. State transitions happen at the right granularity: `thinking` the moment the query is sent, `speaking` on the first text token (not after the full response), `searching` only when a web search tool fires.

---

## Threading Model

```
Main Thread                    Background Thread
───────────                    ─────────────────
pywebview event loop           asyncio event loop
(Windows requires GUI           ├── agent queries
 on main thread)                ├── voice capture (to_thread)
                                ├── TTS playback (to_thread)
                                ├── memory I/O
                                └── distillation tasks
          ◄──── InterruptController ────►
          (threading.Event + asyncio.Event)
```

`InterruptController` bridges both worlds — `fire()` is thread-safe (callable from pywebview or sounddevice threads), `is_interrupted` is a cheap poll for blocking code, and `wait()` is for async coroutines.

---

## Data Layout

Everything persists under `~/.noaises/` (configurable via `NOAISES_HOME`):

```
~/.noaises/
├── memory/
│   ├── long_term.md                    # Permanent knowledge
│   └── short_term/
│       └── 2026-02-15.md              # Daily observations
├── sessions/
│   └── 2026-02-15.jsonl               # Conversation log (append-only)
├── personality/
│   └── personality_evolution.json      # Learned traits + tone shifts
└── artifacts/
    └── screenshots/                    # Auto-cleaned after 1 hour
```

---

## Configuration

`src/noaises/config.py` uses Pydantic settings (env vars override defaults):

| Setting | Default | Purpose |
|---|---|---|
| `NOAISES_HOME` | `~/.noaises` | Data directory |
| `enable_streaming` | `True` | Token-by-token output + streaming TTS |
| `memory_distill_enabled` | `True` | Background memory consolidation |
| `memory_distill_interval` | `5` | Distill every N turns |
| `memory_distill_model` | `claude-haiku-4-5-20251001` | Model for distillation |

---

## Goals & Roadmap

What we're building toward — a companion that feels less like software and more like a presence.

### Personality Evolution
The personality engine already tracks traits and tone shifts. Next: **adaptive personality** that genuinely changes based on interaction patterns — becoming more technical with a developer, more casual over time, developing inside jokes. The companion should feel different after 100 conversations than after 10.

### Endless Single Session
Today each turn is a one-shot query (system prompt rebuilt per turn with memory context). The goal: a **persistent conversational thread** where context accumulates naturally within a session, with memory acting as long-term compression rather than a per-turn workaround. The companion should remember what you said 5 minutes ago without needing to retrieve it.

### Proactive Interactions
The companion shouldn't only respond — it should **initiate**. Time-based check-ins ("You've been at this for 3 hours, want to take a break?"), context-based suggestions ("I noticed you're working on the same file as yesterday — want me to pull up where you left off?"), and ambient awareness of the user's state.

### Local Models
Currently, all inference goes through the Claude API. The vision: **bring critical paths local**. Local Whisper STT is already done. Next targets: local TTS (reduced latency, no cloud dependency), local small model for quick tasks (memory distillation, intent classification), with Claude reserved for complex reasoning.

### Bring Your Own Model
Not everyone wants Claude. The agent core should support **pluggable model backends** — OpenAI, Gemini, local Ollama, or any OpenAI-compatible API. The personality, memory, and voice layers are model-agnostic by design; only the agent core needs abstraction.

### Voice Tuning
Voice is identity. Goals: **voice cloning** (ElevenLabs or local), **emotion-aware prosody** (excited responses sound excited), **multilingual voice switching** (match the user's language automatically), and **wake word detection** for hands-free activation without push-to-talk.

### Custom MCP Tools
The agent can already use Bash, Read, Write, WebSearch, and memory tools. Next: **user-defined MCP tools** for system integration — calendar access, email, smart home control, IDE integration. The companion becomes a true desktop assistant, not just a conversationalist.

### Ambient Intelligence
Screen capture intent detection is a start. The full vision: **continuous ambient awareness** — understanding what app is focused, what the user is working on, offering help without being asked. Privacy-first: all processing local, user controls what the companion can see.

---

## Project Structure

```
noaises-local/
├── src/noaises/
│   ├── main.py                  # Orchestrator — turn loop, wiring, shutdown
│   ├── config.py                # Pydantic settings
│   ├── logger.py                # Structured JSON logging
│   │
│   ├── agent/core.py            # Claude SDK wrapper — streaming + batch
│   │
│   ├── voice/
│   │   ├── stt.py               # Whisper STT (local, faster-whisper)
│   │   ├── tts.py               # Azure TTS + StreamingTTSSession
│   │   └── pipeline.py          # VAD, barge-in, sentence buffer
│   │
│   ├── memory/
│   │   ├── model.py             # Pydantic models (ShortTerm, LongTerm)
│   │   ├── store.py             # Markdown persistence
│   │   ├── distiller.py         # Background consolidation (Haiku)
│   │   └── tools.py             # MCP server (memory_store, memory_remove)
│   │
│   ├── personality/engine.py    # TOML config + evolution + prompt building
│   ├── sessions/engine.py       # Daily JSONL conversation logs
│   ├── interrupt/controller.py  # Thread-safe interrupt signaling
│   │
│   ├── surface/
│   │   ├── desktop.py           # pywebview wrapper
│   │   └── web/                 # HTML/CSS/JS persona animations
│   │
│   └── tools/screen_capture.py  # Screen capture + intent detection
│
├── config/personality.toml      # Personality configuration
├── pyproject.toml               # Dependencies + build config
└── README.md                    # You are here
```

---

## Development

```bash
uv sync                    # Install/update dependencies
uv run noaises             # Run the companion
uv add <package>           # Add a dependency
uv run python -m pytest    # Run tests
```

**Requirements**: Python 3.11+, managed with [uv](https://docs.astral.sh/uv/).

---

*Built with obsessive attention to latency, local-first principles, and the belief that AI companions should have personality — not just capability.*
