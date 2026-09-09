import { useEffect, useState } from "react";
import { api, type Health, type Settings as SettingsData } from "../lib/api";
import { Button, Card, Pill, Spinner, cx } from "../components/ui";

const DESCRIPTIONS: Record<string, string> = {
  claude_code: "Your local Claude Code CLI. No API key, uses your subscription.",
  cursor:
    "Cursor models (Grok 4.6, Composer). Needs CURSOR_API_KEY from cursor.com/dashboard/integrations — the IDE login is not reused.",
  anthropic: "The Anthropic API directly. Needs ANTHROPIC_API_KEY.",
  openai: "The OpenAI API. Needs OPENAI_API_KEY.",
  ollama: "A local model via Ollama. Fully offline.",
  manual: "No LLM. Studying, search, and manual entry still work.",
};

export function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(true);
  const [cursorKey, setCursorKey] = useState("");
  const [savingKey, setSavingKey] = useState(false);

  useEffect(() => {
    api.settings().then(setSettings).catch(() => undefined);
    api
      .health()
      .then(setHealth)
      .catch(() => undefined)
      .finally(() => setChecking(false));
  }, []);

  if (!settings) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const current = settings;

  async function choose(provider: string) {
    const next = {
      provider,
      ...(provider === "cursor" ? { cursor_model: current.cursor_model || "grok-4.6" } : {}),
    };
    setSettings((value) => (value ? { ...value, ...next } : value));
    await api.saveSettings(next);
    setChecking(true);
    setHealth(await api.health().catch(() => null));
    setChecking(false);
  }

  async function chooseCursorModel(cursor_model: string) {
    setSettings((value) => (value ? { ...value, provider: "cursor", cursor_model } : value));
    await api.saveSettings({ provider: "cursor", cursor_model });
    setChecking(true);
    setHealth(await api.health().catch(() => null));
    setChecking(false);
  }

  async function saveCursorKey() {
    const key = cursorKey.trim();
    if (!key) return;
    setSavingKey(true);
    await api.saveSettings({ provider: "cursor", cursor_key: key });
    setCursorKey("");
    setSettings((value) => (value ? { ...value, provider: "cursor", cursor_key_configured: true } : value));
    setChecking(true);
    setHealth(await api.health().catch(() => null));
    setChecking(false);
    setSavingKey(false);
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-8 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-dim">Provider</h2>
        <ul className="mt-3 space-y-2">
          {settings.providers.map((provider) => (
            <li key={provider}>
              <button
                onClick={() => choose(provider)}
                className={cx(
                  "w-full rounded-card border px-4 py-3 text-left transition-colors",
                  settings.provider === provider
                    ? "border-accent bg-accent-soft"
                    : "border-border bg-surface hover:border-border-strong",
                )}
              >
                <span className="font-mono text-sm text-text">{provider}</span>
                <span className="mt-0.5 block text-xs text-faint">
                  {DESCRIPTIONS[provider]}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {settings.provider === "cursor" && (
        <section className="mt-8">
          <h2 className="text-sm font-medium text-dim">Cursor model</h2>
          <ul className="mt-3 flex flex-wrap gap-2">
            {(settings.cursor_models ?? []).map((model) => (
              <li key={model.id}>
                <button
                  onClick={() => chooseCursorModel(model.id)}
                  className={cx(
                    "rounded-lg border px-3 py-2 text-left transition-colors",
                    settings.cursor_model === model.id
                      ? "border-accent bg-accent-soft text-text"
                      : "border-border bg-surface text-dim hover:border-border-strong hover:text-text",
                  )}
                >
                  <span className="block text-sm">{model.label}</span>
                  <span className="font-mono text-[11px] text-faint">{model.id}</span>
                </button>
              </li>
            ))}
          </ul>

          <h2 className="mt-8 text-sm font-medium text-dim">Cursor API key</h2>
          <p className="mt-1 text-xs text-faint">
            Create a user API key at cursor.com/dashboard/integrations. Being signed in to
            Cursor here is not enough. The key is stored only on this Mac at
            ~/.config/ultralearn/env.
          </p>
          {settings.cursor_key_configured && (
            <p className="mt-2 text-xs text-accent">A key is configured for this session.</p>
          )}
          <div className="mt-3 flex gap-2">
            <input
              type="password"
              autoComplete="off"
              value={cursorKey}
              onChange={(event) => setCursorKey(event.target.value)}
              placeholder="cursor_…"
              className="h-11 min-w-0 flex-1 rounded-card border border-border bg-surface px-4 font-mono text-sm text-text placeholder:text-faint focus:border-accent focus:outline-none"
            />
            <Button
              disabled={!cursorKey.trim() || savingKey}
              onClick={() => void saveCursorKey()}
            >
              {savingKey ? "Saving…" : "Save key"}
            </Button>
          </div>
        </section>
      )}

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-dim">Status</h2>
          {checking ? (
            <Spinner />
          ) : (
            <Button
              size="sm"
              onClick={async () => {
                setChecking(true);
                setHealth(await api.health().catch(() => null));
                setChecking(false);
              }}
            >
              Re-check
            </Button>
          )}
        </div>
        <Card className="mt-3">
          {health ? (
            <>
              <div className="flex items-center gap-2">
                <Pill tone={health.ready ? "accent" : "wrong"}>
                  {health.ready ? "ready" : "not ready"}
                </Pill>
                <span className="font-mono text-sm text-dim">{health.provider}</span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-dim">{health.message}</p>
            </>
          ) : checking ? (
            <Spinner label="Checking the provider…" />
          ) : (
            <p className="text-sm text-faint">Status unavailable.</p>
          )}
        </Card>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-dim">Where your data lives</h2>
        <Card className="mt-3">
          <p className="font-mono text-xs break-all text-dim">{settings.db_path}</p>
          <p className="mt-2 text-xs text-faint">
            One SQLite file, never uploaded anywhere. Copy it to move your history to
            another machine.
          </p>
        </Card>
      </section>
    </div>
  );
}
