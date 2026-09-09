import { useEffect, useMemo, useState } from "react";
import { api, type Concept, type SearchHit, type Source } from "../lib/api";
import { Bar, Button, Card, Empty, Pill, Spinner, cx } from "../components/ui";

export function Library({
  onFocus,
  onGenerated,
  onCode,
  onMath,
}: {
  onFocus: (query: string) => void;
  onGenerated: () => void;
  onCode?: (conceptId: number) => void;
  onMath?: (conceptId: number) => void;
}) {
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [tab, setTab] = useState<"concepts" | "sources">("concepts");
  const [generating, setGenerating] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([api.concepts(), api.sources()])
      .then(([nextConcepts, nextSources]) => {
        setConcepts(nextConcepts);
        setSources(nextSources);
      })
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    if (!query.trim()) {
      setHits([]);
      setSearched(false);
      return;
    }
    const timer = window.setTimeout(() => {
      api
        .search(query)
        .then((next) => {
          setHits(next);
          setSearched(true);
        })
        .catch(() => {
          setHits([]);
          setSearched(true);
        });
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

      {searched && query.trim() && hits.length === 0 && (
        <div className="mt-4">
          <Empty title="Nothing matches that.">
            Try a concept name, or describe the idea in your own words.
          </Empty>
        </div>
      )}

      {hits.length > 0 && (
        <ul className="mt-4 space-y-2">
          {hits.map((hit) => (
            <li key={`${hit.kind}-${hit.ref_id}`}>
              <Card className="p-4">
                <div className="flex items-center gap-2">
                  <Pill>{hit.kind}</Pill>
                  {hit.via && hit.via !== "text" && (
                    <Pill tone="info">{hit.via}</Pill>
                  )}
                  <p className="text-sm font-medium text-text">{hit.title}</p>
                </div>
                <p className="mt-1.5 text-sm leading-relaxed text-dim">{hit.snippet}</p>
                {hit.kind === "concept" && (
                  <Button
                    size="sm"
                    className="mt-3"
                    onClick={() => onFocus(hit.title)}
                  >
                    Practice this
                  </Button>
                )}
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
        !loaded ? (
          <div className="mt-10 flex justify-center">
            <Spinner label="Reading the library…" />
          </div>
        ) : sorted.length === 0 ? (
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
                <Button size="sm" onClick={() => onFocus(concept.title)}>
                  Practice
                </Button>
                {onCode && (concept.code_count ?? 0) > 0 && (
                  <Button size="sm" onClick={() => onCode(concept.id)}>
                    Code
                  </Button>
                )}
                {onMath && (concept.math_count ?? 0) > 0 && (
                  <Button size="sm" onClick={() => onMath(concept.id)}>
                    Math
                  </Button>
                )}
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
      ) : !loaded ? (
        <div className="mt-10 flex justify-center">
          <Spinner label="Reading the library…" />
        </div>
      ) : sources.length === 0 ? (
        <div className="mt-6">
          <Empty title="No sources yet." />
        </div>
      ) : (
        <ul className="mt-4 divide-y divide-border">
          {sources.map((source) => (
            <li key={source.id} className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-[15px] text-text">{source.title}</p>
                <p className="mt-0.5 text-[11px] text-faint">
                  {source.type}
                  {source.author ? ` · ${source.author}` : ""} · {source.chunk_count}{" "}
                  passages
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <Button
                  size="sm"
                  disabled={generating === source.id}
                  onClick={() => {
                    setGenerating(source.id);
                    api
                      .generateFromSource(source.id)
                      .then(() => onGenerated())
                      .finally(() => setGenerating(null));
                  }}
                >
                  {generating === source.id ? "Queuing…" : "Write more questions"}
                </Button>
                <span className="tabular text-[11px] text-faint">
                  {source.created_at.slice(0, 10)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
