import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, subscribeToJobs, type Job, type Question } from "./lib/api";
import { Study } from "./screens/Study";
import { RoundSummary, Today } from "./screens/Today";
import { Ingest } from "./screens/Ingest";
import { Library } from "./screens/Library";
import { Progress } from "./screens/Progress";
import { Settings } from "./screens/Settings";
import { Code } from "./screens/Code";
import { MathGym } from "./screens/Math";
import { Spinner, cx } from "./components/ui";

type View = "today" | "code" | "math" | "add" | "library" | "progress" | "settings";
type Round =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "active"; items: Question[] }
  | { state: "summary"; outcomes: Array<{ question: Question; correct: boolean }> }
  | { state: "empty" };

const NAV: Array<{
  id: View;
  label: string;
  hint: string;
  key: string;
  digit: string;
  group: "study" | "library" | "meta";
  icon: IconName;
}> = [
  { id: "today", label: "Today", hint: "What to do now", key: "t", digit: "1", group: "study", icon: "today" },
  { id: "code", label: "Code", hint: "PyTorch and ML drills", key: "c", digit: "2", group: "study", icon: "code" },
  { id: "math", label: "Math", hint: "Say the formula out loud", key: "m", digit: "3", group: "study", icon: "math" },
  { id: "library", label: "Library", hint: "Everything ingested", key: "l", digit: "4", group: "library", icon: "library" },
  { id: "add", label: "Add", hint: "Drop a file or link", key: "a", digit: "5", group: "library", icon: "add" },
  { id: "progress", label: "Progress", hint: "Weak spots", key: "p", digit: "6", group: "meta", icon: "progress" },
  { id: "settings", label: "Settings", hint: "Provider and data", key: "g", digit: "7", group: "meta", icon: "settings" },
];

export default function App() {
  const [view, setView] = useState<View>("today");
  const [round, setRound] = useState<Round>({ state: "idle" });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [codeConceptId, setCodeConceptId] = useState<number | null>(null);
  const [mathConceptId, setMathConceptId] = useState<number | null>(null);

  useEffect(() => subscribeToJobs(setJobs), []);

  const go = useCallback((next: View) => {
    setView(next);
    if (next !== "code") setCodeConceptId(null);
    if (next !== "math") setMathConceptId(null);
  }, []);

  const begin = useCallback(async (kind: "session" | "drill" | "focus", query?: string) => {
    setRound({ state: "loading" });
    try {
      const response =
        kind === "drill"
          ? await api.drill()
          : kind === "focus" && query
            ? await api.focus(query)
            : await api.session();
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

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === "TEXTAREA" || target?.tagName === "INPUT") return;
      if (target?.closest("[contenteditable], .cm-editor")) return;
      if (studying || event.metaKey || event.ctrlKey) return;

      const destination = NAV.find(
        (item) => item.key === event.key.toLowerCase() || item.digit === event.key,
      );
      if (destination) {
        event.preventDefault();
        go(destination.id);
        return;
      }
      if (event.key.toLowerCase() === "s" && view === "today") {
        event.preventDefault();
        void begin("session");
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [begin, go, studying, view]);

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
  const studyItems = NAV.filter((item) => item.group === "study");
  const libraryItems = NAV.filter((item) => item.group === "library");
  const metaItems = NAV.filter((item) => item.group === "meta");

  return (
    <div className="flex h-full">
      <nav className="flex w-56 shrink-0 flex-col border-r border-border bg-surface px-3 py-5">
        <div className="px-2">
          <p className="text-[15px] font-semibold tracking-tight">Ultralearn</p>
          <p className="mt-0.5 text-[11px] text-faint">your local teacher</p>
        </div>

        <NavGroup label="Study">
          {studyItems.map((item) => (
            <NavButton
              key={item.id}
              item={item}
              active={view === item.id}
              onClick={() => go(item.id)}
            />
          ))}
        </NavGroup>

        <NavGroup label="Library">
          {libraryItems.map((item) => (
            <NavButton
              key={item.id}
              item={item}
              active={view === item.id}
              onClick={() => go(item.id)}
            />
          ))}
        </NavGroup>

        <div className="mt-auto">
          {active.length > 0 && (
            <button
              onClick={() => go("add")}
              className="mb-3 w-full px-2 text-left"
              title={active.map((job) => job.detail).join("\n")}
            >
              <Spinner
                label={`${active.length} job${active.length === 1 ? "" : "s"} running`}
              />
            </button>
          )}
          <ul className="space-y-0.5">
            {metaItems.map((item) => (
              <NavButton
                key={item.id}
                item={item}
                active={view === item.id}
                onClick={() => go(item.id)}
              />
            ))}
          </ul>
        </div>
      </nav>

      <main
        className={cx(
          "flex-1",
          view === "code" || view === "math" ? "overflow-hidden" : "overflow-y-auto",
        )}
      >
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
            onIngest={() => go("add")}
            onCode={() => go("code")}
            onMath={() => go("math")}
            onFocus={(query) => begin("focus", query)}
            onGenerateFocus={(query) => {
              void api.generateFromFocus(query);
              go("add");
            }}
          />
        )}
        {view === "code" && (
          <Code
            conceptId={codeConceptId}
            onClearConcept={() => setCodeConceptId(null)}
          />
        )}
        {view === "math" && (
          <MathGym
            conceptId={mathConceptId}
            onClearConcept={() => setMathConceptId(null)}
          />
        )}
        {view === "add" && <Ingest />}
        {view === "library" && (
          <Library
            onFocus={(query) => begin("focus", query)}
            onCode={(conceptId) => {
              setCodeConceptId(conceptId);
              setView("code");
            }}
            onMath={(conceptId) => {
              setMathConceptId(conceptId);
              setView("math");
            }}
            onGenerated={() => go("add")}
          />
        )}
        {view === "progress" && <Progress />}
        {view === "settings" && <Settings />}
      </main>
    </div>
  );
}

function NavGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mt-6">
      <p className="px-3 text-[10px] font-medium tracking-[0.14em] text-faint uppercase">
        {label}
      </p>
      <ul className="mt-1.5 space-y-0.5">{children}</ul>
    </div>
  );
}

function NavButton({
  item,
  active,
  onClick,
}: {
  item: (typeof NAV)[number];
  active: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        onClick={onClick}
        title={`${item.hint} · ${item.key.toUpperCase()}`}
        className={cx(
          "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
          active
            ? "bg-accent-soft text-text ring-1 ring-accent/30"
            : "text-dim hover:bg-raised/70 hover:text-text",
        )}
      >
        <NavIcon name={item.icon} className={active ? "text-accent" : "text-faint"} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm">{item.label}</span>
          <span className="block truncate text-[11px] text-faint">{item.hint}</span>
        </span>
        <span className="font-mono text-[10px] text-faint/80">{item.key.toUpperCase()}</span>
      </button>
    </li>
  );
}

type IconName = "today" | "code" | "math" | "library" | "add" | "progress" | "settings";

function NavIcon({ name, className }: { name: IconName; className?: string }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    className,
    "aria-hidden": true,
  };
  if (name === "today") {
    return (
      <svg {...common}>
        <rect x="4" y="5" width="16" height="15" rx="2" />
        <path d="M8 3v4M16 3v4M4 10h16" />
      </svg>
    );
  }
  if (name === "code") {
    return (
      <svg {...common}>
        <path d="M8 8 4 12l4 4M16 8l4 4-4 4M14 6l-4 12" />
      </svg>
    );
  }
  if (name === "math") {
    return (
      <svg {...common}>
        <path d="M5 5h14L12 12l7 7H5" />
      </svg>
    );
  }
  if (name === "library") {
    return (
      <svg {...common}>
        <path d="M5 5v14M9 5v14M13 5l6 14M13 5v14" />
      </svg>
    );
  }
  if (name === "add") {
    return (
      <svg {...common}>
        <path d="M12 5v14M5 12h14" />
      </svg>
    );
  }
  if (name === "progress") {
    return (
      <svg {...common}>
        <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 4v2M12 18v2M4 12h2M18 12h2M6.2 6.2l1.4 1.4M16.4 16.4l1.4 1.4M6.2 17.8l1.4-1.4M16.4 7.6l1.4-1.4" />
    </svg>
  );
}
