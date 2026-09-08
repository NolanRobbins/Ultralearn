# Ultralearn

A local-first personal teacher. Feed it book notes, chapters, and papers; it works out
what is worth ingraining, tests you on it properly, and keeps bringing it back until
you actually know it.

Everything stays on your machine. It drives your local Claude Code CLI by default, so
there is no API key and no metered usage.

```bash
uv sync --extra desktop
uv run ultralearn
```

See [SETUP.md](SETUP.md) for the full setup, and [SPEC.md](SPEC.md) for what this is
meant to be and why it is built this way.

## How it works

**Add material once.** Drop a PDF, EPUB, Markdown file, or a link (arXiv included) onto
the Add screen. A background job extracts the text, chunks it, has the model identify
the concepts worth learning, classifies the topic, writes questions for each concept,
drops near-duplicates, and saves. No forms to fill in, and nothing to approve — you can
study while it runs.

**Spaced repetition is scheduled on concepts, not questions.** The scheduler decides
which *idea* is due; the question testing it is chosen or written at review time. Ideas
resurface on schedule while the wording keeps changing, so you cannot pattern-match your
way through a review.

**Free recall is the default.** You type the answer. An examiner grades it against a
strict rubric and returns a verdict, a score, what you left out, the specific
misconception your answer reveals, a probe, and a fix. A correct label with no mechanism
is marked partial. Multiple choice exists, but as the warmup.

**Misconceptions are first-class.** When the examiner names one, it becomes a row in the
database that resurfaces on the concept, feeds a dedicated drill session, and retires
only after you answer cleanly. You can also miss something confidently — being sure and
wrong costs more than being unsure and wrong, and the Progress screen shows you where
your confidence is not earned.

**The interface never waits on a model.** Every LLM call is a background job with live
progress. The study loop is fully keyboard-driven: `1`–`5` set confidence, `A`–`E` pick
options, `⌘↵` submits a written answer, `↵` advances, `Esc` leaves.

## Screens

- **Today** — one question answered: what should I do right now. Due count, time
  estimate, streak, and 30 days of activity.
- **Study** — one question at a time, centred, with the examiner's feedback inline.
- **Add** — the drop zone and the job queue.
- **Library** — full-text and semantic search across everything ingested, with mastery
  per concept and coverage per source.
- **Progress** — mastery by topic, calibration, open misconceptions, weakest concepts,
  and an on-demand diagnostic report.

## Architecture

The Python engine (`ultralearn/`) holds all the learning logic and is independent of any
UI. `ultralearn/api/` puts HTTP in front of it, `ultralearn/jobs.py` runs anything slow
in the background, and `desktop/` is a React frontend served in a native window. The
shell is deliberately thin, so it can be swapped without touching the UI.

Data lives in one SQLite file, `ultralearn.db`, beside the code. Copy that file to move
your history to another machine.

## Without an LLM

Set the provider to `manual` and studying, search, statistics, and manual question entry
all keep working. Only generation and grading need a model.

## Tests

```bash
uv run pytest
```
