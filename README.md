# Ultralearn

Ultralearn is a local-first personal teacher for active recall, spaced repetition, Feynman explanations, and weak-spot drilling.

## Run

```bash
pip install -r requirements.txt
streamlit run ultralearn_app.py
```

The app stores data in `ultralearn.db` beside the code. It defaults to the Claude Code CLI provider (`claude -p`) when available, but the study loop, source storage, manual entry, search, and dashboard all work without an LLM provider.

## Study: 10-question quiz rounds

The Study page runs fixed 10-question rounds. Click "Take the quiz" to start; each round blends due concepts, weak spots, and leeches. Multiple-choice questions are answered with a single click on the option, written formats reveal the expected answer and are self-graded strictly, and every answer is logged into concept-level SM-2 automatically. A progress bar tracks the round, and the end-of-round summary shows your score and which concepts will come back soon, with a "10 more questions" button to keep going.

When "Generate fresh question variants during the quiz" is on (and a provider is available), any question you've seen before is replaced with a newly written variant of the same concept, so ideas resurface on schedule but the wording keeps changing.

## Focus: semantic search over your library

The Study page has a Focus box: describe what you want to work on ("sensor fusion failure modes", "pot odds vs implied odds") and Ultralearn retrieves the closest concepts and passages from every source using a local vector index over chunks and concepts. From there you can start a focused quiz round on the matched concepts, or generate 10 brand-new questions from the matched passages — even when they span multiple overlapping sources.

Embeddings are stored in the `embeddings` table and refreshed lazily whenever content changes. If `sentence-transformers` is installed, true semantic vectors (MiniLM, fully local) are used; otherwise a dependency-free keyword-vector fallback keeps Focus working with approximate matching. Fresh question variants also use this index: when a concept has no linked passage, the closest passages across all sources provide the generation context, and newly saved questions link each concept to the chunk of its source that matches it best.

## Generation batches and usage

Question generation always runs in rounds of 10, produced in batches of 5 per LLM call so no single call is large enough to hit a timeout. Progress and per-batch usage are shown live, and later batches are told which prompts already exist so they steer away from repeats. The sidebar keeps a running total of LLM calls, time, tokens, and cost for the session (cost/tokens come from Claude Code's JSON output; other providers report duration only). The per-call timeout defaults to 300s and is adjustable in Settings.

## Ingest PDFs

Open the Ingest page and drop a PDF into the "Drop a PDF" uploader. Ultralearn extracts selectable text locally, puts it into the Text box for inspection/editing, and then you can save the source or generate questions from it.

Scanned image-only PDFs are not supported yet because they need OCR.

## Providers

Set providers in the app Settings page or with environment variables:

```bash
export ULTRALEARN_PROVIDER=claude_code
export CLAUDE_CODE_COMMAND=claude
export ULTRALEARN_MODEL=claude-sonnet-4-6
```

Available providers are `claude_code`, `anthropic`, `openai`, `ollama`, and `manual`. API keys can be entered in Settings or supplied with `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.

## Data Model

The scheduler operates on `concepts`, not specific questions. Sources are stored as chunked text, concepts link back to chunks, and many question variants can test one concept. Reviews update concept-level SM-2 fields and mastery, so old ideas keep resurfacing while wording can keep changing.

If an old `ultralearn.db` with `cards` and card-level `reviews` exists, startup migrates it once into the new schema. The original `cards` table is left in place, and old reviews are preserved as `legacy_reviews`.

## Tests

```bash
python -m pytest
```
