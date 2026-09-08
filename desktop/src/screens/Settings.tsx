import { useEffect, useState } from "react";
import { api, type Health, type Settings as SettingsData } from "../lib/api";
import { Button, Card, Pill, Spinner, cx } from "../components/ui";

const DESCRIPTIONS: Record<string, string> = {
  claude_code: "Your local Claude Code CLI. No API key, uses your subscription.",
  anthropic: "The Anthropic API directly. Needs ANTHROPIC_API_KEY.",
  openai: "The OpenAI API. Needs OPENAI_API_KEY.",
  ollama: "A local model via Ollama. Fully offline.",
  manual: "No LLM. Studying, search, and manual entry still work.",
};

export function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    api.settings().then(setSettings).catch(() => undefined);
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  if (!settings) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }

  async function choose(provider: string) {
    setSettings((current) => (current ? { ...current, provider } : current));
    await api.saveSettings({ provider });
    setChecking(true);
    setHealth(await api.health().catch(() => null));
    setChecking(false);
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
