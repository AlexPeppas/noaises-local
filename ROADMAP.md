# noaises — Roadmap

> Evolving from AI assistant to fully autonomous companion.

---

## Vision

noaises is not a chatbot. It's a persistent, evolving digital companion that sees, hears, remembers, and grows alongside you. It maintains a single continuous thread of consciousness — no session boundaries, no cold starts. It manages its own cognitive resources like a living being: thinking hard when it matters, coasting on instinct when it doesn't, and resting when it needs to consolidate.

---

## In Progress

### Camera & Vision
*Currently being built in a parallel branch.*

- Live camera/webcam capture pipeline
- Visual context fed alongside voice input — noaises can see the user and their environment
- Multimodal perception: hear + see simultaneously during interaction
- Privacy-first: all processing local, frames never leave the machine

---

## Planned

### 1. Eternal Session

noaises maintains one singular, unbroken context — not a series of disposable conversations. Like a human mind, it accumulates experience throughout the day and consolidates it during rest.

**How it works:**
- Single continuous session that spans the lifetime of the companion
- Context grows naturally through interaction during the day
- **Nightly consolidation**: at end-of-day (or when idle), noaises compresses the day's raw context into distilled memories — facts learned, preferences updated, emotional beats, unfinished threads
- Post-consolidation, the working context resets to a compact seed: identity + long-term memory + distilled session summary
- The raw conversation history moves to cold storage (JSONL archives) — retrievable but not loaded by default
- No "new session" concept from the user's perspective — noaises always picks up where it left off

**Key design decisions:**
- Consolidation is a background process, not a user-facing action
- The distiller evolves from periodic extraction to a proper end-of-day synthesis pass
- Session continuity metadata tracks what noaises "knows it knows" vs. what got archived

---

### 2. Local Model Router

Stop using Opus as a hammer for every nail. Route queries to the right model based on complexity, saving tokens, latency, and compute.

**Architecture:**
- **Complexity classifier** — lightweight heuristic or small model that scores incoming queries (simple acknowledgment vs. deep reasoning vs. tool-heavy task)
- **Model tiers:**
  - **Tier 1 — Local small** (e.g. Qwen 2.5, Phi-3, Gemma): casual conversation, simple Q&A, acknowledgments, quick memory lookups
  - **Tier 2 — Cloud mid** (e.g. Haiku, Sonnet): moderate reasoning, summarization, memory distillation
  - **Tier 3 — Cloud heavy** (e.g. Opus): complex multi-step reasoning, tool orchestration, nuanced conversation
- **Smart resource management** — only one local model loaded in VRAM at a time. Hot-swap between local models with a small latency penalty rather than keeping multiple models resident. The token budget savings must not be offset by local GPU/RAM bloat.
- **Graceful fallback** — if the local model produces low-confidence output, escalate to a higher tier transparently

**Key design decisions:**
- Router must be fast — classification overhead should be negligible compared to inference
- User never sees the routing; noaises just "thinks at the right level"
- Config-driven tier definitions so users can plug in their own local models
- Track per-tier usage stats for the stamina UI

---

### 3. Token Stamina Bar

Surface noaises' cognitive budget as an intuitive game-like UI element. The user sees a living being with finite energy, not a stateless API.

**UX concept:**
- **Stamina bar** rendered below the persona figure — a horizontal bar that starts full and drains as the context fills
- Drain rate reflects actual token usage: heavy reasoning and long exchanges drain faster, quick exchanges barely move it
- **Visual states tied to stamina:**
  - **Full (100-70%)** — alert, responsive, energetic animations
  - **Mid (70-30%)** — normal, steady
  - **Low (30-10%)** — visibly tired, slower animations, subtle visual cues
  - **Critical (<10%)** — triggers compaction. noaises enters a **resting state**: eyes close, ambient animation, "consolidating..." indicator
- **During rest**: stamina bar slowly refills as background compaction runs. Once compaction completes, noaises "wakes up" with a fresh context and full stamina
- The bar is driven by real metrics: `tokens_used / max_context_tokens`

**Key design decisions:**
- Compaction is triggered automatically at a configurable threshold (default ~10%)
- The user can also manually trigger rest ("take a break", "go rest")
- Stamina refill speed reflects actual compaction progress, not a fake timer
- The resting state is a real functional pause — noaises doesn't accept new input until compaction completes (or offers degraded short-context responses from a local model while the main context compacts)

---

## Future Ideas

- **Proactive behavior** — noaises initiates conversation based on time of day, observed patterns, or unfinished threads from memory
- **Emotional modeling** — internal emotional state influenced by interaction tone, time of day, and stamina level, reflected in voice prosody and animations
- **Multi-room awareness** — if multiple cameras/mics available, understand spatial context
- **Skill acquisition** — noaises learns to use new tools and workflows by watching the user, not just by being programmed
- **Companion-to-companion** — multiple noaises instances sharing memories or context (e.g. work companion and home companion with a shared identity core)
