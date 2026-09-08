# Setup

Getting Ultralearn running on a new machine.

## 1. Python environment

Ultralearn targets Python 3.11+ and uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

That installs the core engine and API. The heavier pieces are optional extras, so a
fresh clone stays small:

```bash
uv sync --extra desktop      # native app window (pywebview)
uv sync --extra semantic     # true embeddings via sentence-transformers (~2GB, pulls torch)
uv sync --extra epub         # EPUB ingestion
```

Without the `semantic` extra, Focus search falls back to a dependency-free
keyword-vector index. It still works; matches are just approximate.

## 2. Claude Code

Ultralearn drives your local Claude Code CLI by default, so generation and grading
run on your existing subscription rather than a metered API key.

```bash
claude update
claude -p "reply with OK"    # confirm you are logged in
```

**The update matters.** Ultralearn asks the CLI for schema-conforming output via
`--json-schema`, which eliminates the malformed-JSON failures that plagued earlier
versions. That flag landed in Claude Code v2.1.205. On older CLIs Ultralearn detects
its absence and falls back to parsing free-form JSON, which is measurably less
reliable. Check with `claude --version`.

Ultralearn deliberately does *not* pass `--bare`, because bare mode never reads OAuth
credentials and would force an `ANTHROPIC_API_KEY`. It instead isolates each call with
`--strict-mcp-config`, empty `--setting-sources`, and a full tool denylist, and runs in
a scratch directory so your `CLAUDE.md` and project settings never leak into a prompt.

## 3. Run it

```bash
uv run ultralearn              # native desktop window
uv run ultralearn --browser    # same app, in your default browser
```

### Working on the frontend

The UI is a Vite + React app in `desktop/`. For hot reload, run the API and the
dev server side by side:

```bash
uv run ultralearn-api                      # prints the API token
cd desktop && npm install && npm run dev    # http://localhost:5173
```

Vite proxies `/api` to the backend. Paste the printed token into the dev URL once
(`http://localhost:5173/?token=…`); it is kept in sessionStorage after that.

To bundle the UI into the desktop app, build it — the API serves `desktop/dist`
automatically when it exists:

```bash
cd desktop && npm run build
```

## 4. Your data

Study data lives in `ultralearn.db` beside the code and is **not** tracked by git. To
carry your history to another machine, copy that one file across. Everything else in
the repo rebuilds from source.

If you point Ultralearn at an old database containing `cards` and card-level `reviews`,
startup migrates it once into the concept-centred schema. The original `cards` table is
left untouched and old reviews are preserved as `legacy_reviews`.

## 5. Tests

```bash
uv run pytest
```

## Configuration

Settings can come from the app's Settings screen or the environment:

```bash
export ULTRALEARN_PROVIDER=claude_code        # claude_code | anthropic | openai | ollama | manual
export ULTRALEARN_MODEL=claude-sonnet-4-6
export CLAUDE_CODE_COMMAND=claude
export ULTRALEARN_DB=/path/to/ultralearn.db
export ULTRALEARN_PROVIDER_TIMEOUT=300
```

API keys for the Anthropic and OpenAI providers are read from `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY`, or entered in Settings.
