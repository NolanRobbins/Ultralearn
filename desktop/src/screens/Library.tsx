import { useEffect, useMemo, useState } from "react";
import { api, type Concept, type SearchHit, type Source } from "../lib/api";
import { Bar, Card, Empty, Pill, cx } from "../components/ui";

export function Library() {
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [tab, setTab] = useState<"concepts" | "sources">("concepts");

  useEffect(() => {
    api.concepts().then(setConcepts).catch(() => undefined);
    api.sources().then(setSources).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!query.trim()) {
      setHits([]);
      return;
    }
    // Debounced so typing does not fire a query per keystroke.
    const timer = window.setTimeout(() => {
      api.search(query).then(setHits).catch(() => undefined);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  const sorted = useMemo(
    () => [...concepts].sort((a, b) => a.mastery - b.mastery),
    [concepts],
  );

  return (
    <div className="mx-auto w-full max-w-4xl px-8 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Library</h1>

      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search everything you have ingested…"
        className="mt-6 h-11 w-full rounded-card border border-border bg-surface px-4 text-[15px] text-text placeholder:text-faint focus:border-accent focus:outline-none"
      />

      {hits.length > 0 && (
        <ul className="mt-4 space-y-2">
          {hits.map((hit) => (
            <li key={`${hit.kind}-${hit.ref_id}`}>
              <Card className="p-4">
                <div className="flex items-center gap-2">
                  <Pill>{hit.kind}</Pill>
                  <p className="text-sm font-medium text-text">{hit.title}</p>
                </div>
                <p className="mt-1.5 text-sm leading-relaxed text-dim">{hit.snippet}</p>
              </Card>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-8 flex gap-1 border-b border-border">
        {(["concepts", "sources"] as const).map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            className={cx(
              "-mb-px border-b-2 px-4 py-2 text-sm capitalize transition-colors",
              tab === name
                ? "border-accent text-text"
                : "border-transparent text-faint hover:text-dim",
            )}
          >
            {name}
            <span className="tabular ml-2 text-xs text-faint">
              {name === "concepts" ? concepts.length : sources.length}
            </span>
          </button>
        ))}
      </div>

      {tab === "concepts" ? (
        sorted.length === 0 ? (
          <div className="mt-6">
            <Empty title="No concepts yet.">Add material and they appear here.</Empty>
          </div>
        ) : (
          <ul className="mt-4 divide-y divide-border">
            {sorted.map((concept) => (
              <li key={concept.id} className="flex items-center gap-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-[15px] text-text">{concept.title}</p>
                    {concept.leech && <Pill tone="wrong">leech</Pill>}
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-faint">
                    {concept.topic_slug} · due {concept.due} ·{" "}
                    {concept.question_count} question
                    {concept.question_count === 1 ? "" : "s"}
                  </p>
                </div>
                <div className="w-28 shrink-0">
                  <Bar
                    value={concept.mastery}
                    tone={
                      concept.mastery >= 0.75
                        ? "correct"
                        : concept.mastery >= 0.4
                          ? "partial"
                          : "wrong"
                    }
                  />
                  <p className="tabular mt-1 text-right text-[11px] text-faint">
                    {Math.round(concept.mastery * 100)}%
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )
      ) : sources.length === 0 ? (
        <div className="mt-6">
          <Empty title="No sources yet." />
        </div>
      ) : (
        <ul className="mt-4 divide-y divide-border">
          {sources.map((source) => (
            <li key={source.id} className="flex items-center justify-between py-3">
              <div className="min-w-0">
                <p className="truncate text-[15px] text-text">{source.title}</p>
                <p className="mt-0.5 text-[11px] text-faint">
                  {source.type}
                  {source.author ? ` · ${source.author}` : ""} · {source.chunk_count}{" "}
                  passages
                </p>
              </div>
              <span className="tabular shrink-0 text-[11px] text-faint">
                {source.created_at.slice(0, 10)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
