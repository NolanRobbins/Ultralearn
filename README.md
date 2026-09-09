# Ultralearn

A local-first personal teacher. Feed it book notes, chapters, and papers; it works out
what is worth ingraining, tests you on it properly, and keeps bringing it back until
you actually know it.

Everything stays on your machine. Generation and grading talk to a local provider —
Cursor (Grok 4.6 by default when a `CURSOR_API_KEY` is present), your Claude Code CLI,
Anthropic, OpenAI, Ollama, or manual mode with no model at all.

```bash
uv sync --extra desktop --extra cursor --extra semantic --extra epub
cd desktop && npm install && npm run build
uv run ultralearn --browser
```

See [SETUP.md](SETUP.md) for a new-machine walkthrough, and [SPEC.md](SPEC.md) for what
this is meant to be and why it is built this way.

## How it works

**Add material once.** Drop a PDF, EPUB, Markdown file, Word doc, or a link (arXiv
included) onto the Add screen. A background job extracts the text, chunks it, has the
model identify the concepts worth learning, classifies the topic, writes questions for
each concept, drops near-duplicates, and saves. No forms to fill in, and nothing to
approve — you can study while it runs.

**Spaced repetition is scheduled on concepts, not questions.** The scheduler decides
which *idea* is due; the question testing it is chosen or written at review time. Ideas
resurface on schedule while the wording keeps changing, so you cannot pattern-match your
way through a review.

**Free recall is the default.** You type the answer. An examiner grades it against a
strict rubric and returns a verdict, a score, what you left out, the specific
misconception your answer reveals, a probe, and a fix. A correct label with no mechanism
is marked partial. Multiple choice exists, but as the warmup. After a miss, a probe
question is mandatory before you can continue.

**Misconceptions are first-class.** When the examiner names one, it becomes a row in the
database that resurfaces on the concept, feeds a dedicated drill session, and retires
only after you answer cleanly. You can also miss something confidently — being sure and
wrong costs more than being unsure and wrong, and the Progress screen shows you where
your confidence is not earned.

**Code and Math are gyms, not flashcards.** Code drills are local PyTorch / ML / LLM
functions with hidden tests, in an editor with IDE-style highlighting. Math drills show
a formula in LaTeX; you say it in English, fill a missing piece, and explain why a term
is there. Linked drills attach to concepts from your library. You can also ask the
model to write a new formula drill from ingested notes.

**The interface never waits on a model.** Every LLM call is a background job with live
progress. The study loop is fully keyboard-driven: `1`–`5` set confidence, `A`–`E` pick
options, `⌘↵` submits a written answer, `↵` advances, `Esc` leaves. Letter keys jump
screens when you are not studying: `T` Today, `C` Code, `M` Math, `L` Library, `A` Add,
`P` Progress, `G` Settings.

## Screens

- **Today** — one question answered: what should I do right now. Due count, time
  estimate, streak, and 30 days of activity. Shortcuts into Code and Math when those
  gyms have work.
- **Study** — one question at a time, centred, with the examiner's feedback inline.
- **Code** — implement a function; hidden checks run on this machine.
- **Math** — read a formula the way you would say it, then unpack why each piece is there.
- **Add** — the drop zone and the job queue.
- **Library** — full-text and semantic search across everything ingested, with mastery
  per concept and coverage per source. Concepts with linked drills offer Code / Math.
- **Progress** — mastery by topic, calibration, open misconceptions, weakest concepts,
  and an on-demand diagnostic report.
- **Settings** — provider, Cursor model, and the Cursor API key (stored only in
  `~/.config/ultralearn/env`).

## Architecture

The Python engine (`ultralearn/`) holds all the learning logic and is independent of any
UI. `ultralearn/api/` puts HTTP in front of it, `ultralearn/jobs.py` runs anything slow
in the background, and `desktop/` is a React frontend served in a native window (or the
browser). The shell is deliberately thin, so it can be swapped without touching the UI.

Data lives in one SQLite file, `ultralearn.db`, beside the code. Copy that file to move
your history to another machine. It is gitignored.

## Secrets

Do not put keys in the repo. Ultralearn reads, in order:

1. The process environment
2. A local `.env` next to the repo (gitignored)
3. `~/.config/ultralearn/env` (mode 600) — this is what Settings writes

`CURSOR_API_KEY` comes from [cursor.com/dashboard/integrations](https://cursor.com/dashboard/integrations).
Logging into the Cursor IDE is not enough; the SDK cannot reuse that session. A helper
at `scripts/save-cursor-key.sh` writes the key to the config file above.

Each launch binds a one-time loopback token (`?token=`). It is not a stored secret, but
do not paste that URL into chat, tickets, or git.

## Without an LLM

Set the provider to `manual` and studying, search, statistics, Code checks, Math phrase
grading, and manual question entry all keep working. Only generation and the written
examiner need a model.

## Tests

```bash
uv run pytest
cd desktop && npm run build
```
