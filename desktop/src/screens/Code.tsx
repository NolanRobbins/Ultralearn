import { useEffect, useMemo, useState } from "react";
import {
  api,
  type CodeProblem,
  type CodeRunResult,
} from "../lib/api";
import { Button, Empty, Pill, Spinner, cx } from "../components/ui";
import { PythonEditor } from "../components/PythonEditor";

export function Code({
  conceptId,
  onClearConcept,
}: {
  conceptId?: number | null;
  onClearConcept?: () => void;
}) {
  const [problems, setProblems] = useState<CodeProblem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<"all" | "linked" | "fundamentals" | "pytorch" | "llm">(
    conceptId ? "linked" : "all",
  );
  const [activeId, setActiveId] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [result, setResult] = useState<CodeRunResult | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setFilter(conceptId ? "linked" : "all");
  }, [conceptId]);

  useEffect(() => {
    api
      .codeProblems(conceptId ?? undefined)
      .then((next) => {
        setProblems(next);
        const preferred =
          next.find((item) => item.last_passed === false) ??
          next.find((item) => !item.ever_passed) ??
          next[0];
        if (preferred) {
          setActiveId(preferred.id);
          setCode(preferred.last_code || preferred.starter);
        }
      })
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, [conceptId]);

  const active = problems.find((item) => item.id === activeId) ?? null;

  const visible = useMemo(() => {
    return problems.filter((item) => {
      if (filter === "linked") return Boolean(item.concept_id);
      if (filter === "fundamentals") return !item.concept_id;
      if (filter === "pytorch") return item.tags.includes("pytorch");
      if (filter === "llm") return item.tags.includes("llm") || item.tags.includes("attention");
      return true;
    });
  }, [filter, problems]);

  function open(problem: CodeProblem) {
    setActiveId(problem.id);
    setResult(null);
    setCode(problem.last_code || problem.starter);
  }

  async function run() {
    if (!active || running) return;
    setRunning(true);
    setResult(null);
    try {
      const next = await api.runCode(active.id, code);
      setResult(next);
      setProblems((current) =>
        current.map((item) =>
          item.id === active.id
            ? {
                ...item,
                attempts: item.attempts + 1,
                last_code: code,
                last_passed: next.passed,
                ever_passed: item.ever_passed || next.passed,
              }
            : item,
        ),
      );
    } catch (exception) {
      setResult({
        passed: false,
        checks: [],
        stdout: "",
        stderr: "",
        runtime_ms: 0,
        timed_out: false,
        error: (exception as Error).message,
      });
    } finally {
      setRunning(false);
    }
  }

  if (!loaded) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading coding drills…" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-4 py-4">
          <h1 className="text-lg font-semibold tracking-tight">Code</h1>
          <p className="mt-1 text-xs leading-relaxed text-faint">
            Implement the function. Hidden checks run on this machine — no
            leaderboard, no timer, no accounts.
          </p>
          {conceptId && (
            <button
              className="mt-2 text-xs text-accent hover:underline"
              onClick={onClearConcept}
            >
              Show every drill
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1 px-3 py-3">
          {(
            [
              ["all", "All"],
              ["linked", "Linked"],
              ["fundamentals", "Fundamentals"],
              ["pytorch", "PyTorch"],
              ["llm", "LLM"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setFilter(id)}
              className={cx(
                "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                filter === id
                  ? "border-accent bg-accent-soft text-text"
                  : "border-border text-faint hover:text-dim",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {visible.length === 0 ? (
            <li className="px-2 py-6">
              <Empty title="Nothing in this filter." />
            </li>
          ) : (
            visible.map((problem) => (
              <li key={problem.id}>
                <button
                  onClick={() => open(problem)}
                  className={cx(
                    "mb-1 w-full rounded-lg px-3 py-2.5 text-left transition-colors",
                    problem.id === activeId
                      ? "bg-raised text-text"
                      : "text-dim hover:bg-raised/60 hover:text-text",
                  )}
                >
                  <span className="block truncate text-sm">{problem.title}</span>
                  <span className="mt-1 flex items-center gap-2 text-[11px] text-faint">
                    <span className="capitalize">{problem.difficulty}</span>
                    {problem.concept_title && (
                      <span className="truncate">{problem.concept_title}</span>
                    )}
                    {problem.ever_passed && <span className="text-accent">solved</span>}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        {active ? (
          <>
            <header className="shrink-0 border-b border-border px-6 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold">{active.title}</h2>
                <Pill tone={active.difficulty === "easy" ? "accent" : active.difficulty === "hard" ? "wrong" : "partial"}>
                  {active.difficulty}
                </Pill>
                {active.tags.map((tag) => (
                  <Pill key={tag}>{tag}</Pill>
                ))}
              </div>
              {active.concept_title && (
                <p className="mt-1 text-xs text-faint">
                  Linked to {active.concept_title}
                </p>
              )}
              <p className="mt-3 max-w-3xl text-[15px] leading-relaxed text-dim">
                {active.prompt}
              </p>
            </header>

            <div className="grid min-h-0 flex-1 grid-rows-[1fr_auto] lg:grid-cols-[1fr_20rem] lg:grid-rows-1">
              <div className="flex min-h-0 flex-col border-b border-border lg:border-r lg:border-b-0">
                <div className="flex items-center justify-between border-b border-border px-4 py-2">
                  <p className="font-mono text-[11px] text-faint">solution.py</p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={() => {
                        setCode(active.starter);
                        setResult(null);
                      }}
                    >
                      Reset
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={running || !code.trim()}
                      onClick={() => void run()}
                    >
                      {running ? "Running…" : "Run checks"}
                    </Button>
                  </div>
                </div>
                <div className="min-h-0 flex-1 bg-[#0b0e13]">
                  <PythonEditor value={code} onChange={setCode} onRun={() => void run()} />
                </div>
                <p className="shrink-0 border-t border-border px-4 py-2 text-[11px] text-faint">
                  Tab indents · colored like an editor · ⌘↵ runs locally
                </p>
              </div>

              <div className="min-h-40 overflow-y-auto px-4 py-4">
                <h3 className="text-[11px] font-medium uppercase tracking-wider text-faint">
                  Checks
                </h3>
                {running && (
                  <div className="mt-4">
                    <Spinner label="Running on this machine…" />
                  </div>
                )}
                {!running && !result && (
                  <p className="mt-3 text-sm text-dim">
                    Hidden tests import your functions and assert against a
                    reference. Run to see which ones pass.
                  </p>
                )}
                {result && (
                  <div className="mt-3 space-y-3">
                    <p
                      className={cx(
                        "text-sm font-semibold",
                        result.passed ? "text-correct" : "text-wrong",
                      )}
                    >
                      {result.timed_out
                        ? "Timed out"
                        : result.passed
                          ? "All checks passed"
                          : result.error || "Some checks failed"}
                      <span className="ml-2 font-normal text-faint">
                        {result.runtime_ms}ms
                      </span>
                    </p>
                    <ul className="space-y-2">
                      {result.checks.map((item) => (
                        <li
                          key={item.name}
                          className="rounded-lg border border-border bg-raised px-3 py-2"
                        >
                          <p
                            className={cx(
                              "text-sm",
                              item.ok ? "text-correct" : "text-wrong",
                            )}
                          >
                            {item.ok ? "Pass" : "Fail"} · {item.name}
                          </p>
                          {item.error && (
                            <p className="mt-1 font-mono text-[11px] leading-relaxed text-dim">
                              {item.error}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                    {result.stderr && (
                      <pre className="overflow-x-auto font-mono text-[11px] whitespace-pre-wrap text-wrong">
                        {result.stderr}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Empty title="Pick a drill.">Start with softmax if you want a warmup.</Empty>
          </div>
        )}
      </section>
    </div>
  );
}
