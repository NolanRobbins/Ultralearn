# Ultralearn — Product Spec

The living specification. Supersedes the original build handoff prompt.

## What this is

A local-first personal teacher. It takes everything fed into it — book notes, chapters,
papers, scratch notes — and ingrains that knowledge through active recall, spaced
repetition, and demanding feedback. It tests new material *and* keeps resurfacing old
material, learns weak spots over time, and never lets the learner coast.

This is long-term software, run for years across an AI/ML learning journey (deep
learning, math, statistics, GPU optimization, plus adjacent tracks like options and
poker theory). It is not a throwaway script.

## Guiding philosophy

Built on Scott Young's ultralearning principles plus core learning science. Every
feature serves at least one:

- **Retrieval** — testing beats rereading; default to making the learner produce answers.
- **Retention** — spacing fights the forgetting curve; old material must keep returning.
- **Directness** — test understanding in the form it will be used: application, diagnosis, comparison. Not definitions.
- **Drill** — isolate the weakest sub-skills and hammer them.
- **Feedback** — intense and honest, never ego-pleasing; expose misconceptions.
- **Intuition (Feynman)** — make the learner explain in their own words, then probe the explanation.
- **Metalearning** — show what to study and why.
- **Focus / Experimentation** — sessions sustain momentum and vary.

## The core design rule

**Spaced repetition is scheduled on concepts, never on questions.**

The scheduler decides which *concept* is due. The generator then writes or selects a
question for that concept at review time. This decouples "what needs revisiting" from
"the exact wording seen," so ideas resurface on schedule while the phrasing keeps
changing and pattern-matching stays impossible. The scheduler never needs to know a
specific question exists.

## Why v0.2 exists

v0.1 met every acceptance criterion in the original handoff and was still abandoned
after a single day of use — 1 source, 11 concepts, 2 reviews. The features were not the
problem. Three things broke the loop, and v0.2 targets exactly those.

### 1. LLM calls could not be trusted

The Claude Code provider shelled out to `claude -p <prompt> --output-format json` with
no isolation and no output schema. Every call loaded a full agent session: user-level
`CLAUDE.md`, custom agents, the plugin tree. The model free-wrote JSON into prose and
the app string-parsed it. Result: 300-second hangs and `Expecting ',' delimiter` errors
mid-session.

**Fix.** Isolate every call (`--strict-mcp-config`, empty `--setting-sources`, full tool
denylist, scratch working directory, prompt on stdin). Pass the configured model and a
fallback model. Feature-detect `--json-schema` and use it so the CLI returns validated
`structured_output`. Keep a repair-and-retry path for providers without schema support.
Never pass `--bare` — it disables OAuth and would force a metered API key.

### 2. Ingestion was work

Getting material in required source type, title, author, identifier, topic slug and
Bloom bias, then a blocking generation call of up to five minutes, then a Keep checkbox
on each of ten questions, then Save.

**Fix.** One drop zone. Drop a file, folder, or URL and a background pipeline extracts
text, chunks it, has the model extract *concepts*, auto-assigns topics, generates and
dedups questions, and saves them. No forms. Review is an optional audit, not a gate.

### 3. The testing was not demanding

The rigorous examiner existed but sat behind an optional expander, and written answers
were graded by the learner clicking "I got it." The `reviews.critique` column was never
written. Misconceptions were shown once and discarded.

**Fix.** Free recall becomes the default and MCQ the warmup. Grading returns a strict
schema — verdict, score, what was missing, the exact misconception, a probe, a fix —
which is parsed and persisted. Named misconceptions become first-class rows that get
re-tested until retired. A missed concept triggers a mandatory probe before advancing.

### And the UI had a hard ceiling

Streamlit reruns the whole page on every interaction and cannot bind keystrokes, so
"fast, keyboard-friendly answering" was never achievable. The repeated "I can't read the
sidebar" complaints were a design-token problem that ad-hoc CSS could not fix.

**Fix.** A React frontend in a native window, with an explicit token system meeting
WCAG AA contrast, and full keyboard control of the study loop.

## Architecture

```
┌─────────────────────────────────────────────┐
│  Native window (pywebview; Tauri-swappable)  │
│  React + TypeScript + Tailwind               │
└────────────────────┬─────────────────────────┘
                     │  HTTP + SSE
┌────────────────────▼─────────────────────────┐
│  FastAPI  ·  ultralearn/api/                 │
└──────┬──────────────────────────┬────────────┘
       │                          │
┌──────▼───────────┐    ┌─────────▼────────────┐
│  Engine          │    │  Job queue + worker  │
│  scheduler       │    │  ultralearn/jobs/    │
│  learner         │    └─────────┬────────────┘
│  generation      │              │
│  dedup           │    ┌─────────▼────────────┐
│  embeddings      │    │  providers.py        │
└──────┬───────────┘    │  Claude Code CLI     │
       │                └─────────┬────────────┘
┌──────▼──────────────────────────▼────────────┐
│  SQLite  ·  ultralearn.db                    │
└──────────────────────────────────────────────┘
```

**The UI never waits on an LLM.** Every provider call is a job with observable progress.
Ingestion and generation run while the learner studies.

All learning logic stays independent of the UI, so the frontend can be replaced without
rewriting the scheduler, data model, or providers. The shell is a thin swappable layer:
the React app is identical under pywebview, Tauri, or a plain browser.

## Data model

- `sources` — type, title, author, identifier, tags, metadata, date added.
- `content_chunks` — the raw ingested text, chunked, linked to its source. Kept so material can be re-queried and regenerated from later.
- `concepts` — the central unit. One idea or skill being ingrained. Carries SM-2 state (ease / interval / repetitions / due), mastery, topic, and links to source chunks.
- `concept_chunks` — which passages a concept came from.
- `questions` — many per concept, each tracing back to its source chunk. Interchangeable tests *of* the concept, which is what makes fresh-variant generation safe.
- `reviews` — per answer: correctness, pre-answer confidence, derived SM-2 quality, latency, the answer text, and the examiner's structured critique.
- `misconceptions` — named misconceptions, re-tested until retired.
- `jobs` — background work with status and progress.
- `topics` — a slug taxonomy (`dl`, `math`, `gpu`, `stats`, `options`, `poker`, extensible) with sub-topics.
- `embeddings` — local vectors over chunks and concepts for semantic retrieval.
- `search_fts` — FTS5 full-text search over sources, chunks, and concepts.

## Providers

All LLM access sits behind one `Provider` interface: `generate_questions`, `critique`,
`analyze_weakspots`.

- **`claude_code` (default)** — drives the local Claude Code CLI in headless mode. No API key, uses the existing subscription.
- **`anthropic` / `openai`** — API SDK fallbacks.
- **`ollama`** — fully offline local models.
- **`manual`** — no LLM. Study, storage, search, and manual entry all still work.

Anything that can work offline still does.

## Definition of done

- Material can be added by dropping a file, folder, or URL, with no forms, and it persists, is searchable, and traces back to its source.
- Knowledge is organized as concepts, and spaced repetition is scheduled at the concept level, so due concepts resurface while the questions testing them keep changing.
- Generated questions vary in type and phrasing and do not repeat.
- Generation and grading run through the local Claude Code setup with no API key, and do not fail on malformed JSON or hang.
- Sessions automatically mix new, spaced, and weak-spot material, and the app can say specifically and honestly where the learner is weak and what to study next.
- Written answers are graded by a demanding examiner that names the misconception, and those misconceptions come back until they are resolved.
- The study loop is fully keyboard-driven and responds instantly.
- It is pleasant enough that the learner keeps coming back — measured by review count and active days, not by feature count.

## Deliberately deferred

FSRS scheduling, Anki export, and OCR for scanned PDFs. The concept-level SM-2
implementation is sound and is not what limited usage.
