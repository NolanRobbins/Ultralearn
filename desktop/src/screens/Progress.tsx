import { useEffect, useState } from "react";
import { api, subscribeToJobs, type CoachingReport, type Stats } from "../lib/api";
import { Bar, Button, Card, Empty, Pill, Spinner, cx } from "../components/ui";

export function Progress() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [reports, setReports] = useState<CoachingReport[]>([]);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.stats().then(setStats).catch(() => undefined);
    api.coachingReports().then(setReports).catch(() => undefined);
  }, []);

  // A finished coaching job means there is a new report to pull in.
  useEffect(
    () =>
      subscribeToJobs((jobs) => {
        const latest = jobs.find((job) => job.kind === "coaching");
        if (!latest) return;
        setWorking(latest.status === "queued" || latest.status === "running");
        if (latest.status === "failed") setError(latest.error ?? "The report failed.");
        if (latest.status === "succeeded") {
          api.coachingReports().then(setReports).catch(() => undefined);
        }
      }),
    [],
  );

  if (!stats) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Reading your history…" />
      </div>
    );
  }

  const topics = Object.entries(stats.topic_mastery).sort((a, b) => a[1] - b[1]);

  return (
    <div className="mx-auto w-full max-w-4xl px-8 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Progress</h1>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-dim">Mastery by topic</h2>
        {topics.length === 0 ? (
          <div className="mt-3">
            <Empty title="No reviews yet." />
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {topics.map(([topic, mastery]) => (
              <div key={topic} className="flex items-center gap-4">
                <span className="w-20 shrink-0 font-mono text-xs text-dim">{topic}</span>
                <div className="flex-1">
                  <Bar
                    value={mastery}
                    tone={
                      mastery >= 0.75 ? "correct" : mastery >= 0.4 ? "partial" : "wrong"
                    }
                  />
                </div>
                <span className="tabular w-10 shrink-0 text-right text-xs text-faint">
                  {Math.round(mastery * 100)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-medium text-dim">Calibration</h2>
        <p className="mt-1 text-xs text-faint">
          How often you were right at each confidence level. Being right less often
          than you felt sure is the dangerous direction.
        </p>
        <Calibration data={stats.calibration} />
      </section>

      {stats.misconceptions.length > 0 && (
        <section className="mt-10">
          <h2 className="text-sm font-medium text-dim">Open misconceptions</h2>
          <ul className="mt-3 space-y-2">
            {stats.misconceptions.map((row) => (
              <li key={String(row.id)}>
                <Card className="p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-[15px] leading-relaxed text-text">
                        {String(row.statement)}
                      </p>
                      <p className="mt-1 text-[11px] text-faint">
                        {String(row.concept_title)} · {String(row.topic_slug)}
                      </p>
                    </div>
                    <Pill tone="wrong">seen {String(row.times_seen)}×</Pill>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-10">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-dim">Diagnostic report</h2>
            <p className="mt-1 text-xs text-faint">
              An honest read of what is solid, what is fragile, and what to drill next.
            </p>
          </div>
          {working ? (
            <Spinner label="Writing…" />
          ) : (
            <Button
              size="sm"
              onClick={() => {
                setError("");
                setWorking(true);
                api.requestCoaching().catch((exception) => {
                  setError((exception as Error).message);
                  setWorking(false);
                });
              }}
            >
              {reports.length ? "Write a new one" : "Write one"}
            </Button>
          )}
        </div>
        {error && (
          <p className="mt-3 text-sm text-wrong" role="alert">
            {error}
          </p>
        )}
        {reports[0] ? (
          <Card className="mt-3">
            <p className="text-[11px] text-faint">
              {reports[0].ts.slice(0, 16).replace("T", " ")} · {reports[0].provider}
            </p>
            <pre className="mt-2 font-sans text-[15px] leading-relaxed whitespace-pre-wrap text-dim">
              {reports[0].report}
            </pre>
          </Card>
        ) : (
          !working && (
            <div className="mt-3">
              <Empty title="No report yet." />
            </div>
          )
        )}
      </section>

      {stats.weak_spots.length > 0 && (
        <section className="mt-10">
          <h2 className="text-sm font-medium text-dim">Weakest concepts</h2>
          <ul className="mt-3 divide-y divide-border">
            {stats.weak_spots.map((row) => (
              <li key={String(row.id)} className="flex items-center gap-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] text-text">{String(row.title)}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-faint">
                    {String(row.topic_slug)}
                    {Number(row.overconfident_misses) > 0 &&
                      ` · ${row.overconfident_misses} confident misses`}
                  </p>
                </div>
                {Boolean(row.leech) && <Pill tone="wrong">leech</Pill>}
                <span className="tabular w-12 shrink-0 text-right text-xs text-faint">
                  {Math.round(Number(row.mastery) * 100)}%
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Calibration({ data }: { data: Record<string, number> }) {
  const levels = ["1", "2", "3", "4", "5"];
  const labels: Record<string, string> = {
    "1": "guessing",
    "2": "shaky",
    "3": "decent",
    "4": "sure",
    "5": "certain",
  };
  const hasData = levels.some((level) => data[level] !== undefined);
  if (!hasData) {
    return (
      <div className="mt-3">
        <Empty title="Not enough answers yet." />
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-3">
      {levels.map((level) => {
        const accuracy = data[level];
        if (accuracy === undefined) return null;
        // Confidence 4-5 means "I am sure"; being wrong there is the illusion of
        // knowing, so it is called out rather than shown as a neutral bar.
        const overconfident = Number(level) >= 4 && accuracy < 0.8;
        return (
          <div key={level} className="flex items-center gap-4">
            <span className="w-20 shrink-0 text-xs text-dim">
              <span className="tabular font-semibold">{level}</span> {labels[level]}
            </span>
            <div className="flex-1">
              <Bar value={accuracy} tone={overconfident ? "wrong" : "correct"} />
            </div>
            <span
              className={cx(
                "tabular w-10 shrink-0 text-right text-xs",
                overconfident ? "text-wrong" : "text-faint",
              )}
            >
              {Math.round(accuracy * 100)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
