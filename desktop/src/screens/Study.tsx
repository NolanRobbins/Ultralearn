import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type Grade,
  type Mode,
  type Question,
  type Reveal,
} from "../lib/api";
import { Bar, Button, Kbd, Pill, Spinner, cx } from "../components/ui";

const LETTERS = "ABCDEF";
const CONFIDENCE = [
  { level: 1, label: "guessing" },
  { level: 2, label: "shaky" },
  { level: 3, label: "decent" },
  { level: 4, label: "sure" },
  { level: 5, label: "certain" },
];

type Phase = "answering" | "graded" | "probing";

interface Outcome {
  question: Question;
  correct: boolean;
}

export function Study({
  items,
  onExit,
  onFinished,
}: {
  items: Question[];
  onExit: () => void;
  onFinished: (outcomes: Outcome[]) => void;
}) {
  const [index, setIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>("answering");
  const [confidence, setConfidence] = useState(3);
  const [answer, setAnswer] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [grade, setGrade] = useState<Grade | null>(null);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [grading, setGrading] = useState(false);
  const [probe, setProbe] = useState("");
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [shake, setShake] = useState(false);

  const question = items[index];
  const startedAt = useRef(Date.now());
  const answerRef = useRef<HTMLTextAreaElement>(null);

  const correct = grade ? grade.verdict === "correct" : null;

  useEffect(() => {
    startedAt.current = Date.now();
    setPhase("answering");
    setConfidence(3);
    setAnswer("");
    setSelected([]);
    setGrade(null);
    setReveal(null);
    setProbe("");
    // Written questions get focus immediately: the fastest path to an answer is
    // to start typing, not to reach for the mouse.
    if (question?.written) {
      requestAnimationFrame(() => answerRef.current?.focus());
    }
  }, [index, question?.written]);

  useEffect(() => {
    if (phase === "answering" || !grade) return;
    document.getElementById("study-feedback")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }, [phase, grade]);

  const finish = useCallback(
    async (wasCorrect: boolean, graded: Grade | null, text: string) => {
      setPhase("graded");
      setGrade(
        graded ?? {
          verdict: wasCorrect ? "correct" : "incorrect",
          score: wasCorrect ? 4 : 0,
          missing: [],
          misconception: "",
          probe: "",
          fix: "",
          expected_answer: "",
          explanation: "",
          graded_by: "auto",
        },
      );
      if (!wasCorrect) {
        setShake(true);
        window.setTimeout(() => setShake(false), 420);
      }
      const revealed = await api.reveal(question.id).catch(() => null);
      setReveal(revealed);

      await api
        .review({
          concept_id: question.concept_id,
          question_id: question.id,
          correct: wasCorrect,
          confidence,
          latency_seconds: (Date.now() - startedAt.current) / 1000,
          answer_text: text,
          mode: question.mode as Mode,
          score: graded?.score ?? null,
          graded_by: graded?.graded_by ?? "auto",
          critique: graded ? formatCritique(graded) : "",
          misconception: graded?.misconception ?? "",
        })
        .catch(() => undefined);

      setOutcomes((previous) => [...previous, { question, correct: wasCorrect }]);
    },
    [confidence, question],
  );

  const submitWritten = useCallback(async () => {
    if (!answer.trim() || grading || phase !== "answering") return;
    setGrading(true);
    try {
      const graded = await api.grade(question.id, answer, confidence);
      await finish(graded.verdict === "correct", graded, answer);
    } catch {
      // Grading failed; fall back to showing the reference answer and let the
      // learner judge, rather than silently recording a pass.
      await finish(false, null, answer);
    } finally {
      setGrading(false);
    }
  }, [answer, confidence, finish, grading, phase, question]);

  const chooseOption = useCallback(
    async (optionIndex: number) => {
      if (phase !== "answering") return;
      if (question.question_type === "multi_select") {
        setSelected((current) =>
          current.includes(optionIndex)
            ? current.filter((item) => item !== optionIndex)
            : [...current, optionIndex].sort((a, b) => a - b),
        );
        return;
      }
      const revealed = await api.reveal(question.id);
      setReveal(revealed);
      setSelected([optionIndex]);
      await finish(revealed.answer_index === optionIndex, null, LETTERS[optionIndex]);
    },
    [finish, phase, question],
  );

  const submitSelection = useCallback(async () => {
    if (phase !== "answering" || !selected.length) return;
    const revealed = await api.reveal(question.id);
    setReveal(revealed);
    const expected = revealed.answer_indices.length
      ? revealed.answer_indices
      : revealed.answer_index != null
        ? [revealed.answer_index]
        : [];
    const want = new Set(expected);
    const wasCorrect =
      selected.length === want.size && selected.every((item) => want.has(item));
    await finish(wasCorrect, null, selected.map((item) => LETTERS[item]).join(""));
  }, [finish, phase, question, selected]);

  const advance = useCallback(() => {
    if (index + 1 >= items.length) {
      onFinished(outcomes);
    } else {
      setIndex(index + 1);
    }
  }, [index, items.length, onFinished, outcomes]);

  // A missed concept must be answered again before moving on: the probe is the
  // point at which a misconception actually gets corrected.
  const mustProbe = phase === "graded" && correct === false && Boolean(grade?.probe);

  useKeyboard({
    phase,
    question,
    grading,
    mustProbe,
    probe,
    setConfidence,
    chooseOption,
    submitWritten,
    submitSelection,
    advance,
    startProbe: () => setPhase("probing"),
    onExit,
  });

  if (!question) return null;

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-8 py-6">
      <header className="shrink-0">
        <div className="flex items-center justify-between text-xs text-faint">
          <div className="flex items-center gap-2">
            <Pill tone={question.mode === "drill" ? "wrong" : "faint"}>
              {question.mode === "due"
                ? "due review"
                : question.mode === "drill"
                  ? "drill"
                  : "practice"}
            </Pill>
            <span className="font-mono">{question.topic_slug}</span>
            <span aria-hidden>·</span>
            <span>{question.concept_title}</span>
          </div>
          <div className="tabular flex items-center gap-3">
            <span>
              {index + 1} / {items.length}
            </span>
            <button
              onClick={onExit}
              className="text-faint transition-colors hover:text-text"
            >
              Esc to leave
            </button>
          </div>
        </div>
        <div className="mt-3">
          <Bar value={index / items.length} />
        </div>
      </header>

      <div className="flex-1 overflow-y-auto pt-10 pb-6">
        <h1
          className={cx(
            "font-read text-[26px] leading-[1.4] text-text",
            shake && "animate-wrong",
          )}
          style={{ fontFamily: "var(--font-read)" }}
        >
          {question.prompt}
        </h1>

        {question.misconceptions.length > 0 && phase === "answering" && (
          <div className="mt-5 rounded-card border border-partial/30 bg-partial/5 p-4 animate-rise">
            <p className="text-[11px] font-medium uppercase tracking-wider text-partial">
              You have gotten this wrong before
            </p>
            <ul className="mt-2 space-y-1 text-sm text-dim">
              {question.misconceptions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {phase === "answering" && (
          <ConfidenceRow value={confidence} onChange={setConfidence} />
        )}

        <div className="mt-6">
          {question.written ? (
            <WrittenAnswer
              ref={answerRef}
              value={answer}
              onChange={setAnswer}
              disabled={phase !== "answering"}
              grading={grading}
              onSubmit={submitWritten}
            />
          ) : (
            <Options
              question={question}
              selected={selected}
              reveal={reveal}
              disabled={phase !== "answering"}
              onChoose={chooseOption}
            />
          )}
          {phase === "answering" && question.question_type === "multi_select" && (
            <div className="mt-3 flex items-center justify-between">
              <p className="text-xs text-faint">
                Letters toggle · <Kbd>Enter</Kbd> to submit
              </p>
              <Button
                variant="primary"
                onClick={() => void submitSelection()}
                disabled={!selected.length}
              >
                Submit selection
              </Button>
            </div>
          )}
        </div>

        {phase !== "answering" && grade && (
          <Feedback
            grade={grade}
            reveal={reveal}
            correct={correct}
            phase={phase}
            probe={probe}
            onProbeChange={setProbe}
            onStartProbe={() => setPhase("probing")}
          />
        )}
      </div>

      {phase !== "answering" && (
        <footer className="shrink-0 border-t border-border pt-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-faint">
              {mustProbe && phase === "graded" ? (
                <>
                  Answer the probe before moving on · <Kbd>P</Kbd>
                </>
              ) : phase === "probing" ? (
                <>
                  <Kbd>⌘</Kbd> <Kbd>↵</Kbd> after the probe
                </>
              ) : (
                <>
                  <Kbd>Enter</Kbd> to continue
                </>
              )}
            </p>
            {mustProbe && phase === "graded" ? (
              <Button variant="primary" onClick={() => setPhase("probing")}>
                Answer the probe
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={advance}
                disabled={phase === "probing" && !probe.trim()}
              >
                {index + 1 >= items.length ? "Finish round" : "Next question"}
              </Button>
            )}
          </div>
        </footer>
      )}
    </div>
  );
}

function ConfidenceRow({
  value,
  onChange,
}: {
  value: number;
  onChange: (level: number) => void;
}) {
  return (
    <div className="mt-7">
      <p className="text-[11px] font-medium uppercase tracking-wider text-faint">
        How sure are you? (set before answering)
      </p>
      <div className="mt-2 flex gap-2">
        {CONFIDENCE.map(({ level, label }) => (
          <button
            key={level}
            onClick={() => onChange(level)}
            className={cx(
              "flex-1 rounded-lg border px-3 py-2 text-left transition-colors duration-100",
              value === level
                ? "border-accent bg-accent-soft text-text"
                : "border-border bg-surface text-faint hover:border-border-strong hover:text-dim",
            )}
          >
            <span className="tabular block text-sm font-semibold">{level}</span>
            <span className="block text-[11px]">{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Options({
  question,
  selected,
  reveal,
  disabled,
  onChoose,
}: {
  question: Question;
  selected: number[];
  reveal: Reveal | null;
  disabled: boolean;
  onChoose: (index: number) => void;
}) {
  return (
    <ul className="space-y-2">
      {question.options.map((option, optionIndex) => {
        const answers = new Set(
          reveal
            ? reveal.answer_indices.length
              ? reveal.answer_indices
              : reveal.answer_index != null
                ? [reveal.answer_index]
                : []
            : [],
        );
        const isAnswer = Boolean(reveal) && answers.has(optionIndex);
        const isPicked = selected.includes(optionIndex);
        const pickedWrong = Boolean(reveal) && isPicked && !isAnswer;
        return (
          <li key={option}>
            <button
              disabled={disabled}
              onClick={() => onChoose(optionIndex)}
              className={cx(
                "flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors duration-100",
                "disabled:cursor-default",
                isAnswer
                  ? "border-correct bg-correct/10"
                  : pickedWrong
                    ? "border-wrong bg-wrong/10"
                    : isPicked
                      ? "border-accent bg-accent-soft"
                      : "border-border bg-surface enabled:hover:border-border-strong enabled:hover:bg-raised",
              )}
            >
              <span
                className={cx(
                  "mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded border font-mono text-[11px]",
                  isAnswer
                    ? "border-correct text-correct"
                    : pickedWrong
                      ? "border-wrong text-wrong"
                      : isPicked
                        ? "border-accent text-text"
                        : "border-border text-faint",
                )}
              >
                {LETTERS[optionIndex]}
              </span>
              <span className="text-[15px] leading-relaxed text-text">{option}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function WrittenAnswer({
  ref,
  value,
  onChange,
  disabled,
  grading,
  onSubmit,
}: {
  ref: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  grading: boolean;
  onSubmit: () => void;
}) {
  return (
    <div>
      <textarea
        ref={ref}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        rows={6}
        placeholder="State the mechanism, not the label. Vague answers are marked wrong."
        className={cx(
          "w-full resize-none rounded-card border border-border bg-surface p-4 text-[15px] leading-relaxed",
          "text-text placeholder:text-faint focus:border-accent focus:outline-none disabled:opacity-60",
        )}
      />
      {!disabled && (
        <div className="mt-3 flex items-center justify-between">
          <p className="text-xs text-faint">
            <Kbd>⌘</Kbd> <Kbd>↵</Kbd> to submit
          </p>
          {grading ? (
            <Spinner label="The examiner is reading your answer…" />
          ) : (
            <Button variant="primary" onClick={onSubmit} disabled={!value.trim()}>
              Submit answer
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function Feedback({
  grade,
  reveal,
  correct,
  phase,
  probe,
  onProbeChange,
  onStartProbe,
}: {
  grade: Grade;
  reveal: Reveal | null;
  correct: boolean | null;
  phase: Phase;
  probe: string;
  onProbeChange: (value: string) => void;
  onStartProbe: () => void;
}) {
  const tone =
    grade.verdict === "correct"
      ? "correct"
      : grade.verdict === "partial"
        ? "partial"
        : "wrong";

  return (
    <div
      id="study-feedback"
      className={cx("mt-8 space-y-4", correct ? "animate-correct" : "animate-rise")}
    >
      <div className="flex items-center gap-3">
        <span
          className="text-lg font-semibold capitalize"
          style={{ color: `var(--color-${tone})` }}
        >
          {grade.verdict}
        </span>
        {grade.graded_by === "examiner" && (
          <span className="tabular text-sm text-faint">{grade.score} / 5</span>
        )}
        {grade.graded_by === "self" && <Pill tone="partial">grade this yourself</Pill>}
      </div>

      {grade.missing.length > 0 && (
        <Section title="What your answer left out">
          <ul className="list-disc space-y-1 pl-4">
            {grade.missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Section>
      )}

      {grade.misconception && (
        <Section title="The misconception" tone="wrong">
          {grade.misconception}
        </Section>
      )}

      {reveal?.expected_answer && (
        <Section title="Reference answer">{reveal.expected_answer}</Section>
      )}
      {reveal?.explanation && <Section title="Why">{reveal.explanation}</Section>}
      {grade.fix && <Section title="Fix before moving on">{grade.fix}</Section>}

      {grade.probe && (
        <div className="rounded-card border border-info/30 bg-info/5 p-4">
          <p className="text-[11px] font-medium uppercase tracking-wider text-info">
            Probe
          </p>
          <p className="mt-1.5 text-[15px] leading-relaxed text-text">{grade.probe}</p>
          {phase === "probing" ? (
            <textarea
              autoFocus
              value={probe}
              onChange={(event) => onProbeChange(event.target.value)}
              rows={3}
              placeholder="Answer it now, while the gap is visible."
              className="mt-3 w-full resize-none rounded-lg border border-border bg-surface p-3 text-sm text-text placeholder:text-faint focus:border-info focus:outline-none"
            />
          ) : (
            <Button size="sm" className="mt-3" onClick={onStartProbe}>
              Answer the probe
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  children,
  tone = "faint",
}: {
  title: string;
  children: React.ReactNode;
  tone?: "faint" | "wrong";
}) {
  return (
    <div>
      <p
        className="text-[11px] font-medium uppercase tracking-wider"
        style={{ color: `var(--color-${tone})` }}
      >
        {title}
      </p>
      <div className="mt-1 text-[15px] leading-relaxed text-dim">{children}</div>
    </div>
  );
}

function formatCritique(grade: Grade): string {
  return [
    `VERDICT: ${grade.verdict} (${grade.score}/5)`,
    grade.missing.length ? `MISSING: ${grade.missing.join("; ")}` : "",
    grade.misconception ? `MISCONCEPTION: ${grade.misconception}` : "",
    grade.probe ? `PROBE: ${grade.probe}` : "",
    grade.fix ? `FIX: ${grade.fix}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

/**
 * All study keyboard handling in one place.
 *
 * The whole loop is reachable without the mouse: digits set confidence, letters
 * pick options, Cmd+Enter submits written answers, Enter submits a multi-select
 * or advances, Esc leaves.
 */
function useKeyboard({
  phase,
  question,
  grading,
  mustProbe,
  probe,
  setConfidence,
  chooseOption,
  submitWritten,
  submitSelection,
  advance,
  startProbe,
  onExit,
}: {
  phase: Phase;
  question: Question | undefined;
  grading: boolean;
  mustProbe: boolean;
  probe: string;
  setConfidence: (level: number) => void;
  chooseOption: (index: number) => void;
  submitWritten: () => void;
  submitSelection: () => void;
  advance: () => void;
  startProbe: () => void;
  onExit: () => void;
}) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!question) return;
      const target = event.target as HTMLElement | null;
      const typing = target?.tagName === "TEXTAREA" || target?.tagName === "INPUT";

      if (event.key === "Escape") {
        event.preventDefault();
        onExit();
        return;
      }

      if (phase === "answering") {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          event.preventDefault();
          submitWritten();
          return;
        }
        if (typing || grading) return;

        if (event.key === "Enter" && question.question_type === "multi_select") {
          event.preventDefault();
          submitSelection();
          return;
        }

        if (event.key >= "1" && event.key <= "5") {
          event.preventDefault();
          setConfidence(Number(event.key));
          return;
        }
        const letter = LETTERS.indexOf(event.key.toUpperCase());
        if (!question.written && letter >= 0 && letter < question.options.length) {
          event.preventDefault();
          chooseOption(letter);
        }
        return;
      }

      if (phase === "probing") {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && probe.trim()) {
          event.preventDefault();
          advance();
        }
        return;
      }

      if (mustProbe) {
        if (
          event.key.toLowerCase() === "p" ||
          event.key === "Enter" ||
          event.key === " "
        ) {
          event.preventDefault();
          startProbe();
        }
        return;
      }

      if (typing) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        advance();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    advance,
    chooseOption,
    grading,
    mustProbe,
    onExit,
    phase,
    probe,
    question,
    setConfidence,
    submitSelection,
    startProbe,
    submitWritten,
  ]);
}
