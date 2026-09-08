import { useCallback, useEffect, useState } from "react";
import { api, subscribeToJobs, type Job, type Question } from "./lib/api";
import { Study } from "./screens/Study";
import { RoundSummary, Today } from "./screens/Today";
import { Ingest } from "./screens/Ingest";
import { Library } from "./screens/Library";
import { Progress } from "./screens/Progress";
import { Settings } from "./screens/Settings";
import { Spinner, cx } from "./components/ui";

type View = "today" | "add" | "library" | "progress" | "settings";
type Round =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "active"; items: Question[] }
  | { state: "summary"; outcomes: Array<{ question: Question; correct: boolean }> }
  | { state: "empty" };

const NAV: Array<{ id: View; label: string; key: string }> = [
  { id: "today", label: "Today", key: "1" },
  { id: "add", label: "Add", key: "2" },
  { id: "library", label: "Library", key: "3" },
  { id: "progress", label: "Progress", key: "4" },
  { id: "settings", label: "Settings", key: "5" },
];

export default function App() {
  const [view, setView] = useState<View>("today");
  const [round, setRound] = useState<Round>({ state: "idle" });
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => subscribeToJobs(setJobs), []);

  const begin = useCallback(async (kind: "session" | "drill") => {
    setRound({ state: "loading" });
    try {
      const response = kind === "drill" ? await api.drill() : await api.session();
      setRound(
        response.items.length
          ? { state: "active", items: response.items }
          : { state: "empty" },
      );
    } catch {
      setRound({ state: "empty" });
    }
  }, []);

  const studying = round.state === "active" || round.state === "loading";

  // Global shortcuts, disabled during a round so they cannot fight the study keys.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === "TEXTAREA" || target?.tagName === "INPUT") return;
      if (studying || event.metaKey || event.ctrlKey) return;

      const destination = NAV.find((item) => item.key === event.key);
      if (destination) {
        event.preventDefault();
        setView(destination.id);
        return;
      }
      if (event.key.toLowerCase() === "s" && view === "today") {
        event.preventDefault();
        void begin("session");
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [begin, studying, view]);

  if (round.state === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Building your round…" />
      </div>
    );
  }

  if (round.state === "active") {
    return (
      <Study
        items={round.items}
        onExit={() => setRound({ state: "idle" })}
        onFinished={(outcomes) => setRound({ state: "summary", outcomes })}
      />
    );
  }

  if (round.state === "summary") {
    return (
      <RoundSummary
        outcomes={round.outcomes}
        onAgain={() => begin("session")}
        onDone={() => setRound({ state: "idle" })}
      />
    );
  }

  const active = jobs.filter(
    (job) => job.status === "queued" || job.status === "running",
  );

  return (
    <div className="flex h-full">
      <nav className="flex w-52 shrink-0 flex-col border-r border-border bg-surface px-3 py-6">
        <div className="px-3">
          <p className="text-[15px] font-semibold tracking-tight">Ultralearn</p>
          <p className="mt-0.5 text-[11px] text-faint">
            retrieval · retention · drill
          </p>
        </div>

        <ul className="mt-8 space-y-0.5">
          {NAV.map((item) => (
            <li key={item.id}>
              <button
                onClick={() => setView(item.id)}
                className={cx(
                  "flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors",
                  view === item.id
                    ? "bg-raised text-text"
                    : "text-dim hover:bg-raised/60 hover:text-text",
                )}
              >
                {item.label}
                <span className="kbd">{item.key}</span>
              </button>
            </li>
          ))}
        </ul>

        <div className="mt-auto px-3">
          {active.length > 0 && (
            <button
              onClick={() => setView("add")}
              className="w-full text-left"
              title={active.map((job) => job.detail).join("\n")}
            >
              <Spinner
                label={`${active.length} job${active.length === 1 ? "" : "s"} running`}
              />
            </button>
          )}
        </div>
      </nav>

      <main className="flex-1 overflow-y-auto">
        {round.state === "empty" && view === "today" && (
          <div className="mx-auto mt-8 w-full max-w-4xl px-8">
            <div className="rounded-card border border-partial/40 bg-partial/5 px-4 py-3">
              <p className="text-sm text-partial">
                No questions are available to build a round yet.
              </p>
              <p className="mt-1 text-sm text-dim">
                Add some material and Ultralearn will generate them for you.
              </p>
            </div>
          </div>
        )}

        {view === "today" && (
          <Today
            onStart={() => begin("session")}
            onDrill={() => begin("drill")}
            onIngest={() => setView("add")}
          />
        )}
        {view === "add" && <Ingest />}
        {view === "library" && <Library />}
        {view === "progress" && <Progress />}
        {view === "settings" && <Settings />}
      </main>
    </div>
  );
}
