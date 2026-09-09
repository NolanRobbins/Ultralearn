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
uv sync --extra cursor       # Cursor SDK (Grok, Composer). Needs CURSOR_API_KEY
```

Without the `semantic` extra, Focus search falls back to a dependency-free
keyword-vector index. It still works; matches are just approximate.

A typical full install:

```bash
uv sync --extra desktop --extra cursor --extra semantic --extra epub
```

## 2. Provider

If a `CURSOR_API_KEY` is present, Ultralearn defaults to Cursor and Grok 4.6.
Otherwise it defaults to your local Claude Code CLI. You can always pick a provider
in Settings.

### Cursor

Create an API key at [cursor.com/dashboard/integrations](https://cursor.com/dashboard/integrations).
The Cursor IDE login is **not** reused.

Either paste the key in Settings, or:

```bash
./scripts/save-cursor-key.sh
```

That writes `CURSOR_API_KEY` to `~/.config/ultralearn/env` (mode 600) and sources it
from `~/.zshrc`. Restart Ultralearn so the launch picks it up.

### Claude Code

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

## 3. Frontend

The UI is a Vite + React app in `desktop/`. The desktop window and `--browser` mode
serve `desktop/dist`, so build it at least once:

```bash
cd desktop && npm install && npm run build
```

That bundle includes the Code editor (CodeMirror) and Math formulas (KaTeX).

## 4. Run it

```bash
uv run ultralearn              # native desktop window
uv run ultralearn --browser    # same app, in your default browser
```

`--browser` prints a loopback URL with a per-launch `?token=`. Do not commit, paste,
or screenshot that URL.

### Working on the frontend

Run the API and the Vite dev server side by side:

```bash
uv run ultralearn-api                      # prints the API token
cd desktop && npm install && npm run dev    # http://localhost:5173
```

Vite proxies `/api` to the backend. Paste the printed token into the dev URL once
(`http://localhost:5173/?token=…`); it is kept in sessionStorage after that.

## 5. Your data

Study data lives in `ultralearn.db` beside the code and is **not** tracked by git. To
carry your history to another machine, copy that one file across. Everything else in
the repo rebuilds from source.

If you point Ultralearn at an old database containing `cards` and card-level `reviews`,
startup migrates it once into the concept-centred schema. The original `cards` table is
left untouched and old reviews are preserved as `legacy_reviews`.

## 6. Tests

```bash
uv run pytest
cd desktop && npm run build
```

## Configuration

Settings can come from the app's Settings screen or the environment. Settings persist
keys into `~/.config/ultralearn/env`, not into the repo.

```bash
export ULTRALEARN_PROVIDER=cursor             # cursor | claude_code | anthropic | openai | ollama | manual
export ULTRALEARN_CURSOR_MODEL=grok-4.6
export ULTRALEARN_MODEL=claude-sonnet-4-6
export ULTRALEARN_CLAUDE_MODEL=sonnet
export CLAUDE_CODE_COMMAND=claude
export ULTRALEARN_DB=/path/to/ultralearn.db
export ULTRALEARN_PROVIDER_TIMEOUT=300
export CURSOR_API_KEY=…                       # or use Settings / scripts/save-cursor-key.sh
export ANTHROPIC_API_KEY=…
export OPENAI_API_KEY=…
```

Never commit `.env`, `ultralearn.db`, or `~/.config/ultralearn/env`.
