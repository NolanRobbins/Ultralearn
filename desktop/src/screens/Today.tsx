import { useEffect, useState } from "react";
import { api, type Health, type Today as TodayData } from "../lib/api";
import { Bar, Button, Card, Kbd, Spinner, Stat, cx } from "../components/ui";

/**
 * The home screen answers one question: what should I do right now?
 *
 * Everything else is secondary, so there is exactly one primary action.
 */
export function Today({
  onStart,
  onDrill,
  onIngest,
}: {
  onStart: () => void;
  onDrill: () => void;
  onIngest: () => void;
}) {
  const [data, setData] = useState<TodayData | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.today().then(setData).catch(() => undefined);
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading your library…" />
      </div>
    );
  }

  const empty = data.concepts === 0;
  const nothingDue = data.due === 0 && !empty;

  return (
    <div className="mx-auto w-full max-w-4xl px-8 py-10">
      {health && !health.ready && (
        <div className="mb-6 rounded-card border border-partial/40 bg-partial/5 px-4 py-3 animate-rise">
          <p className="text-sm font-medium text-partial">
            {health.provider} is not ready
          </p>
          <p className="mt-1 text-sm text-dim">{health.message}</p>
          <p className="mt-1 text-xs text-faint">
            Studying, search, and manual entry all keep working without it.
          </p>
        </div>
      )}

      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Today</h1>
        {data.streak_days > 0 && (
          <p className="tabular text-sm text-dim">
            <span className="font-semibold text-accent">{data.streak_days}</span> day
            streak
          </p>
        )}
      </div>

      <Card className="mt-6 border-border-strong bg-gradient-to-b from-raised to-surface p-7">
        {empty ? (
          <>
            <h2 className="text-xl font-semibold">Nothing to study yet</h2>
            <p className="mt-2 max-w-prose text-dim">
              Drop in a chapter, a paper, or your own notes. Ultralearn reads it,
              works out which ideas are worth ingraining, and writes the questions
              itself.
            </p>
            <Button variant="primary" size="lg" className="mt-6" onClick={onIngest}>
              Add your first source
            </Button>
          </>
        ) : nothingDue ? (
          <>
            <h2 className="text-xl font-semibold">Nothing is due</h2>
            <p className="mt-2 max-w-prose text-dim">
              Your schedule is clear. You can still practise your weakest{" "}
              {data.concepts} concepts — practice counts toward mastery without
              pulling the review schedule forward.
            </p>
            <div className="mt-6 flex gap-3">
              <Button variant="primary" size="lg" onClick={onStart}>
                Practise 10 questions
              </Button>
              {data.open_misconceptions > 0 && (
                <Button size="lg" onClick={onDrill}>
                  Drill {data.open_misconceptions} misconception
                  {data.open_misconceptions === 1 ? "" : "s"}
                </Button>
              )}
            </div>
          </>
        ) : (
          <>
            <h2 className="text-xl font-semibold">
              <span className="tabular text-accent">{data.due}</span> concept
              {data.due === 1 ? "" : "s"} due
            </h2>
            <p className="mt-2 max-w-prose text-dim">
              About {data.estimated_minutes} minute
              {data.estimated_minutes === 1 ? "" : "s"} for the next round of 10,
              blending due reviews, your weakest spots, and anything that has
              become a leech.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Button variant="primary" size="lg" onClick={onStart}>
                Start studying
              </Button>
              {data.open_misconceptions > 0 && (
                <Button size="lg" onClick={onDrill}>
                  Drill {data.open_misconceptions} misconception
                  {data.open_misconceptions === 1 ? "" : "s"}
                </Button>
              )}
              <span className="text-xs text-faint">
                <Kbd>S</Kbd> to start
              </span>
            </div>
          </>
        )}
      </Card>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Concepts" value={data.concepts} />
        <Stat label="Questions" value={data.questions} />
        <Stat
          label="Reviewed today"
          value={data.reviewed_today}
          hint={data.reviews > 0 ? `${data.reviews} all time` : undefined}
        />
        <Stat
          label="Leeches"
          value={data.leeches}
          hint={data.leeches > 0 ? "chronically missed" : undefined}
        />
      </div>

      <section className="mt-8">
        <h3 className="text-sm font-medium text-dim">Last 30 days</h3>
        <Activity days={data.recent_days} />
      </section>
    </div>
  );
}

function Activity({ days }: { days: TodayData["recent_days"] }) {
  const peak = Math.max(1, ...days.map((day) => day.reviews));
  return (
    <div className="mt-3 flex items-end gap-[3px]" style={{ height: 64 }}>
      {days.map((day) => {
        const height = day.reviews === 0 ? 2 : Math.max(4, (day.reviews / peak) * 64);
        return (
          <div
            key={day.date}
            title={`${day.date}: ${day.reviews} review${day.reviews === 1 ? "" : "s"}`}
            className={cx(
              "flex-1 rounded-sm transition-colors",
              day.reviews === 0 ? "bg-border" : "bg-accent/70 hover:bg-accent",
            )}
            style={{ height }}
          />
        );
      })}
    </div>
  );
}

export function RoundSummary({
  outcomes,
  onAgain,
  onDone,
}: {
  outcomes: Array<{ question: { concept_title: string }; correct: boolean }>;
  onAgain: () => void;
  onDone: () => void;
}) {
  const score = outcomes.filter((outcome) => outcome.correct).length;
  const total = outcomes.length;
  const accuracy = total ? score / total : 0;
  const missed = outcomes.filter((outcome) => !outcome.correct);

  return (
    <div className="mx-auto w-full max-w-2xl px-8 py-12 animate-rise">
      <p className="text-sm text-faint">Round complete</p>
      <h1 className="tabular mt-1 text-4xl font-semibold">
        {score} / {total}
      </h1>
      <div className="mt-4">
        <Bar
          value={accuracy}
          tone={accuracy >= 0.8 ? "correct" : accuracy >= 0.5 ? "partial" : "wrong"}
        />
      </div>
      <p className="mt-4 max-w-prose text-dim">
        {accuracy >= 0.8
          ? "Strong round. These concepts move further out, so you will see them again later rather than sooner."
          : accuracy >= 0.5
            ? "Mixed round. The concepts you missed have been pulled forward and will come back soon."
            : "Rough round. Everything you missed is now scheduled for drilling — that is the point, not a setback."}
      </p>

      {missed.length > 0 && (
        <div className="mt-8">
          <h2 className="text-sm font-medium text-dim">Coming back soon</h2>
          <ul className="mt-2 space-y-1">
            {[...new Set(missed.map((outcome) => outcome.question.concept_title))].map(
              (title) => (
                <li key={title} className="text-sm text-text">
                  {title}
                </li>
              ),
            )}
          </ul>
        </div>
      )}

      <div className="mt-10 flex gap-3">
        <Button variant="primary" size="lg" onClick={onAgain}>
          10 more questions
        </Button>
        <Button size="lg" onClick={onDone}>
          Done for now
        </Button>
      </div>
    </div>
  );
}
