import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  api,
  subscribeToJobs,
  type MathFormula,
  type MathGrade,
} from "../lib/api";
import { Formula } from "../components/Formula";
import { Button, Empty, Pill, Spinner, cx } from "../components/ui";

type Mode = "speak" | "fill" | "why";
type Filter = "all" | "linked" | "fundamentals" | "dl" | "llm";

export function MathGym({
  conceptId,
  onClearConcept,
}: {
  conceptId?: number | null;
  onClearConcept?: () => void;
}) {
  const [formulas, setFormulas] = useState<MathFormula[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<Filter>(conceptId ? "linked" : "all");
  const [activeId, setActiveId] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("speak");
  const [spoken, setSpoken] = useState("");
  const [blankText, setBlankText] = useState("");
  const [blankIndex, setBlankIndex] = useState(0);
  const [termSymbol, setTermSymbol] = useState("");
  const [why, setWhy] = useState("");
  const [result, setResult] = useState<MathGrade | null>(null);
  const [grading, setGrading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [topic, setTopic] = useState("");

  function load() {
    return api
      .mathFormulas(conceptId ?? undefined)
      .then((next) => {
        setFormulas(next);
        setActiveId((current) => {
          if (current && next.some((item) => item.id === current)) return current;
          const preferred =
            next.find((item) => !item.ever_passed) ?? next[0] ?? null;
          return preferred ? preferred.id : null;
        });
      })
      .catch(() => undefined);
  }

  useEffect(() => {
    setFilter(conceptId ? "linked" : "all");
  }, [conceptId]);

  useEffect(() => {
    setLoaded(false);
    void load().finally(() => setLoaded(true));
  }, [conceptId]);

  useEffect(() => {
    return subscribeToJobs((jobs) => {
      const mine = jobs.filter((job) => job.kind === "generate_math");
      if (mine.some((job) => job.status === "succeeded")) {
        setGenerating(false);
        void load();
      }
      if (mine.some((job) => job.status === "failed")) {
        setGenerating(false);
      }
    });
  }, [conceptId]);

  const active = formulas.find((item) => item.id === activeId) ?? null;

  useEffect(() => {
    setResult(null);
    setSpoken("");
    setBlankText("");
    setBlankIndex(0);
    setWhy("");
    setTermSymbol(active?.terms[0]?.symbol ?? "");
  }, [activeId, mode]);

  const visible = useMemo(() => {
    return formulas.filter((item) => {
      if (filter === "linked") return Boolean(item.concept_id);
      if (filter === "fundamentals") return !item.concept_id;
      if (filter === "dl") return item.tags.includes("dl") || item.tags.includes("optim");
      if (filter === "llm")
        return item.tags.includes("llm") || item.tags.includes("rl") || item.tags.includes("attention");
      return true;
    });
  }, [filter, formulas]);

  const blank = active?.blanks[blankIndex] ?? null;
  const selectedTerm =
    active?.terms.find((term) => term.symbol === termSymbol) ?? active?.terms[0] ?? null;

  function open(formula: MathFormula) {
    setActiveId(formula.id);
    setMode("speak");
  }

  async function submit() {
    if (!active || grading) return;
    setGrading(true);
    setResult(null);
    try {
      const next = await api.gradeMath({
        formula_id: active.id,
        mode,
        spoken,
        blanks: blank ? { [blank.id]: blankText } : {},
        term_symbol: selectedTerm?.symbol ?? "",
        why,
      });
      setResult(next);
      if (next.passed) {
        setFormulas((current) =>
          current.map((item) =>
            item.id === active.id
              ? { ...item, attempts: item.attempts + 1, ever_passed: true }
              : item,
          ),
        );
      }
    } catch (exception) {
      setResult({
        passed: false,
        verdict: "incorrect",
        score: 0,
        hits: [],
        missing: [],
        spoken: "",
        intuition: "",
        blank_results: [],
        term_why: "",
        fix: (exception as Error).message,
      });
    } finally {
      setGrading(false);
    }
  }

  async function writeFormula() {
    if (generating) return;
    setGenerating(true);
    try {
      await api.generateMath({
        conceptId: conceptId ?? undefined,
        query: topic.trim() || undefined,
      });
    } catch (exception) {
      setGenerating(false);
      setResult({
        passed: false,
        verdict: "incorrect",
        score: 0,
        hits: [],
        missing: [],
        spoken: "",
        intuition: "",
        blank_results: [],
        term_why: "",
        fix: (exception as Error).message,
      });
    }
  }

  if (!loaded) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading formulas…" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
        <div className="border-b border-border px-4 py-4">
          <h1 className="text-lg font-semibold tracking-tight">Math</h1>
          <p className="mt-1 text-xs leading-relaxed text-faint">
            Read the equation the way you would say it. Then fill a piece, then
            say why that piece earns its place.
          </p>
          {conceptId && (
            <button
              className="mt-2 text-xs text-accent hover:underline"
              onClick={onClearConcept}
            >
              Show every formula
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1 px-3 py-3">
          {(
            [
              ["all", "All"],
              ["linked", "Linked"],
              ["fundamentals", "Fundamentals"],
              ["dl", "DL"],
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
            visible.map((formula) => (
              <li key={formula.id}>
                <button
                  onClick={() => open(formula)}
                  className={cx(
                    "mb-1 w-full rounded-lg px-3 py-2.5 text-left transition-colors",
                    formula.id === activeId
                      ? "bg-raised text-text"
                      : "text-dim hover:bg-raised/60 hover:text-text",
                  )}
                >
                  <span className="block truncate text-sm">{formula.title}</span>
                  <span className="mt-1 flex items-center gap-2 text-[11px] text-faint">
                    {formula.concept_title && (
                      <span className="truncate">{formula.concept_title}</span>
                    )}
                    {formula.ever_passed && <span className="text-accent">said</span>}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
        <div className="border-t border-border px-3 py-3">
          <p className="text-[11px] text-faint">
            Pull a formula out of something you ingested.
          </p>
          {!conceptId && (
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="GRPO advantages, LayerNorm…"
              className="mt-2 h-8 w-full rounded-md border border-border bg-raised px-2 text-xs text-text placeholder:text-faint focus:border-accent focus:outline-none"
            />
          )}
          <Button
            size="sm"
            className="mt-2 w-full"
            disabled={generating || (!conceptId && !topic.trim())}
            onClick={() => void writeFormula()}
          >
            {generating ? "Writing…" : "Write a formula drill"}
          </Button>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {active ? (
          <>
            <header className="shrink-0 border-b border-border px-6 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold">{active.title}</h2>
                {active.tags.map((tag) => (
                  <Pill key={tag}>{tag}</Pill>
                ))}
              </div>
              {active.concept_title && (
                <p className="mt-1 text-xs text-faint">Linked to {active.concept_title}</p>
              )}
              <div className="formula-board mt-4 overflow-x-auto rounded-xl border border-border bg-raised px-5 py-6">
                <Formula latex={active.latex} />
              </div>
              <div className="mt-4 flex gap-1">
                {(
                  [
                    ["speak", "Say it"],
                    ["fill", "Fill a piece"],
                    ["why", "Why is it there"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    onClick={() => setMode(id)}
                    className={cx(
                      "rounded-full px-3 py-1.5 text-xs transition-colors",
                      mode === id
                        ? "bg-accent-soft text-text ring-1 ring-accent/40"
                        : "text-faint hover:text-dim",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              {mode === "speak" && (
                <SpeakPanel
                  spoken={spoken}
                  onChange={setSpoken}
                  onSubmit={() => void submit()}
                  grading={grading}
                  result={result}
                />
              )}
              {mode === "fill" && blank && (
                <FillPanel
                  blank={blank}
                  index={blankIndex}
                  total={active.blanks.length}
                  value={blankText}
                  onChange={setBlankText}
                  onSubmit={() => void submit()}
                  onNext={() => {
                    setBlankIndex((index) => Math.min(index + 1, active.blanks.length - 1));
                    setBlankText("");
                    setResult(null);
                  }}
                  grading={grading}
                  result={result}
                />
              )}
              {mode === "fill" && !blank && (
                <p className="text-sm text-dim">This formula has no fill-in pieces yet.</p>
              )}
              {mode === "why" && selectedTerm && (
                <WhyPanel
                  terms={active.terms}
                  selected={selectedTerm}
                  onSelect={(symbol) => {
                    setTermSymbol(symbol);
                    setWhy("");
                    setResult(null);
                  }}
                  why={why}
                  onChange={setWhy}
                  onSubmit={() => void submit()}
                  grading={grading}
                  result={result}
                />
              )}
              {mode === "why" && !selectedTerm && (
                <p className="text-sm text-dim">This formula has no terms to unpack yet.</p>
              )}
            </div>
          </>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Empty title="Pick a formula.">Start with softmax if you want a warmup.</Empty>
          </div>
        )}
      </section>
    </div>
  );
}

function SpeakPanel({
  spoken,
  onChange,
  onSubmit,
  grading,
  result,
}: {
  spoken: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  grading: boolean;
  result: MathGrade | null;
}) {
  return (
    <div className="mx-auto w-full max-w-2xl">
      <p className="text-sm text-dim">
        Say the equation out loud in English — the mechanism, not a recitation of
        symbol names. What does each piece do?
      </p>
      <textarea
        value={spoken}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            onSubmit();
          }
        }}
        rows={6}
        placeholder="Say what each piece does, as if you were teaching it."
        className="mt-3 w-full resize-none rounded-xl border border-border bg-raised px-4 py-3 text-[15px] leading-relaxed text-text placeholder:text-faint focus:border-accent focus:outline-none"
      />
      <div className="mt-3 flex items-center gap-3">
        <Button variant="primary" disabled={grading || !spoken.trim()} onClick={onSubmit}>
          {grading ? "Listening…" : "Check what I said"}
        </Button>
        <p className="text-[11px] text-faint">⌘↵ to submit</p>
      </div>
      {result && <GradeCard result={result} kind="speak" />}
    </div>
  );
}

function FillPanel({
  blank,
  index,
  total,
  value,
  onChange,
  onSubmit,
  onNext,
  grading,
  result,
}: {
  blank: { id: string; prompt: string };
  index: number;
  total: number;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onNext: () => void;
  grading: boolean;
  result: MathGrade | null;
}) {
  const piece = result?.blank_results[0];
  const more = index < total - 1;
  return (
    <div className="mx-auto w-full max-w-2xl">
      <p className="text-[11px] font-medium tracking-wider text-faint uppercase">
        Piece {index + 1} of {total}
      </p>
      <p className="mt-2 font-read text-lg text-text">{blank.prompt}</p>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder="Name the missing piece in English or symbols"
        className="mt-4 h-11 w-full rounded-lg border border-border bg-raised px-4 text-[15px] text-text placeholder:text-faint focus:border-accent focus:outline-none"
      />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={grading || !value.trim()} onClick={onSubmit}>
          {grading ? "Checking…" : "Check this piece"}
        </Button>
        {result && more && (
          <Button onClick={onNext}>Next piece</Button>
        )}
      </div>
      {result && (
        <GradeCard result={result} kind="fill">
          {piece?.why && (
            <p className="mt-2 text-sm leading-relaxed text-dim">
              Why it is there: {piece.why}
            </p>
          )}
        </GradeCard>
      )}
    </div>
  );
}

function WhyPanel({
  terms,
  selected,
  onSelect,
  why,
  onChange,
  onSubmit,
  grading,
  result,
}: {
  terms: Array<{ symbol: string; name: string }>;
  selected: { symbol: string; name: string };
  onSelect: (symbol: string) => void;
  why: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  grading: boolean;
  result: MathGrade | null;
}) {
  return (
    <div className="mx-auto w-full max-w-2xl">
      <p className="text-sm text-dim">
        Pick a term. Explain what would break if it were missing — that is why
        it earned its place.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {terms.map((term) => (
          <button
            key={term.symbol}
            onClick={() => onSelect(term.symbol)}
            className={cx(
              "rounded-full border px-3 py-1.5 text-xs transition-colors",
              term.symbol === selected.symbol
                ? "border-accent bg-accent-soft text-text"
                : "border-border text-faint hover:text-dim",
            )}
          >
            {term.name}
          </button>
        ))}
      </div>
      <p className="mt-4 font-read text-lg text-text">
        Why is <span className="text-accent">{selected.name}</span> in the formula?
      </p>
      <textarea
        value={why}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            onSubmit();
          }
        }}
        rows={5}
        placeholder="If this term vanished, the equation would…"
        className="mt-3 w-full resize-none rounded-xl border border-border bg-raised px-4 py-3 text-[15px] leading-relaxed text-text placeholder:text-faint focus:border-accent focus:outline-none"
      />
      <Button
        variant="primary"
        className="mt-3"
        disabled={grading || !why.trim()}
        onClick={onSubmit}
      >
        {grading ? "Checking…" : "Check this why"}
      </Button>
      {result && <GradeCard result={result} kind="why" />}
    </div>
  );
}

function GradeCard({
  result,
  kind,
  children,
}: {
  result: MathGrade;
  kind: Mode;
  children?: ReactNode;
}) {
  return (
    <div
      className={cx(
        "mt-5 rounded-xl border px-4 py-4",
        result.passed ? "border-correct/40 bg-correct/5" : "border-partial/40 bg-partial/5",
        result.passed ? "animate-correct" : "animate-wrong",
      )}
    >
      <p
        className={cx(
          "text-sm font-semibold",
          result.passed ? "text-correct" : "text-partial",
        )}
      >
        {result.passed
          ? kind === "speak"
            ? "That is the equation, said out loud."
            : kind === "fill"
              ? "That piece is right."
              : "That is why it is there."
          : result.fix || "Close — name the mechanism, not just the symbols."}
      </p>
      {result.missing.length > 0 && !result.passed && (
        <p className="mt-2 text-sm text-dim">
          Still missing: {result.missing.join(", ")}
        </p>
      )}
      {children}
      {result.spoken && kind === "speak" && (
        <div className="mt-3">
          <p className="text-[11px] font-medium tracking-wider text-faint uppercase">
            A fluent reading
          </p>
          <p className="mt-1 font-read text-[15px] leading-relaxed text-text">
            {result.spoken}
          </p>
        </div>
      )}
      {result.term_why && kind === "why" && (
        <div className="mt-3">
          <p className="text-[11px] font-medium tracking-wider text-faint uppercase">
            Why it is there
          </p>
          <p className="mt-1 text-sm leading-relaxed text-text">{result.term_why}</p>
        </div>
      )}
      {result.intuition && (
        <div className="mt-3">
          <p className="text-[11px] font-medium tracking-wider text-faint uppercase">
            Why this form exists
          </p>
          <p className="mt-1 text-sm leading-relaxed text-dim">{result.intuition}</p>
        </div>
      )}
    </div>
  );
}
