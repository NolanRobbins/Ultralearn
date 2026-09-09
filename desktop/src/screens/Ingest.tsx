import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeToJobs, type Job } from "../lib/api";
import { Bar, Button, Card, Empty, Pill, cx } from "../components/ui";

/**
 * One drop zone and nothing else.
 *
 * The old ingest flow asked for source type, title, author, identifier, topic
 * slug and Bloom bias, then blocked for minutes, then made you tick a Keep box
 * on every generated question. None of that was a decision worth making, so
 * none of it is asked for. Work continues in the background.
 */
export function Ingest() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [dragging, setDragging] = useState(false);
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.jobs().then(setJobs).catch(() => undefined);
    return subscribeToJobs(setJobs);
  }, []);

  useEffect(() => {
    const el = folderInput.current;
    if (!el) return;
    el.setAttribute("webkitdirectory", "");
    el.setAttribute("directory", "");
  }, []);

  const SUPPORTED = /\.(pdf|epub|docx|md|markdown|txt|rst|html|htm)$/i;

  const submitFiles = useCallback(async (files: FileList | File[]) => {
    setError("");
    const readable = Array.from(files).filter((file) => SUPPORTED.test(file.name));
    const skipped = Array.from(files).length - readable.length;
    if (!readable.length) {
      setError("None of those files are a format Ultralearn can read yet.");
      return;
    }
    for (const file of readable) {
      try {
        await api.ingestFile(file);
      } catch (exception) {
        setError(`${file.name}: ${(exception as Error).message}`);
        return;
      }
    }
    if (skipped > 0) {
      setError(`Skipped ${skipped} unsupported file${skipped === 1 ? "" : "s"}.`);
    }
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(false);
      if (event.dataTransfer.files.length) {
        void submitFiles(event.dataTransfer.files);
        return;
      }
      const dropped = event.dataTransfer.getData("text/plain").trim();
      if (dropped.startsWith("http")) {
        void api.ingestText({ url: dropped }).catch((exception) =>
          setError((exception as Error).message),
        );
      } else if (dropped) {
        setText(dropped);
      }
    },
    [submitFiles],
  );

  return (
    <div className="mx-auto w-full max-w-3xl px-8 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">Add material</h1>
      <p className="mt-2 max-w-prose text-dim">
        Drop it in and walk away. Ultralearn extracts the text, works out which
        ideas are worth ingraining, and writes questions for each one — while you
        study something else.
      </p>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => fileInput.current?.click()}
        className={cx(
          "mt-7 cursor-pointer rounded-card border-2 border-dashed px-6 py-14 text-center transition-colors",
          dragging
            ? "border-accent bg-accent-soft"
            : "border-border bg-surface hover:border-border-strong",
        )}
      >
        <p className="text-text">Drop a file, a folder, or a link</p>
        <p className="mt-1 text-sm text-faint">
          PDF, Word, EPUB, Markdown, HTML, or text · arXiv links work too
        </p>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          accept=".pdf,.epub,.docx,.md,.markdown,.txt,.rst,.html,.htm"
          onChange={(event) => event.target.files && submitFiles(event.target.files)}
        />
        <input
          ref={folderInput}
          type="file"
          hidden
          multiple
          onChange={(event) => event.target.files && submitFiles(event.target.files)}
        />
      </div>

      <div className="mt-3 flex gap-2">
        <Button size="sm" onClick={() => fileInput.current?.click()}>
          Choose files
        </Button>
        <Button size="sm" onClick={() => folderInput.current?.click()}>
          Choose a folder
        </Button>
      </div>

      {error && (
        <p className="mt-3 text-sm text-wrong" role="alert">
          {error}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && url.trim()) {
              void api.ingestText({ url }).then(() => setUrl(""));
            }
          }}
          placeholder="https://arxiv.org/abs/1706.03762"
          className="h-10 flex-1 rounded-lg border border-border bg-surface px-3 text-sm text-text placeholder:text-faint focus:border-accent focus:outline-none"
        />
        <Button
          onClick={() => url.trim() && api.ingestText({ url }).then(() => setUrl(""))}
          disabled={!url.trim()}
        >
          Fetch
        </Button>
      </div>

      <details className="mt-4">
        <summary className="cursor-pointer text-sm text-faint hover:text-dim">
          Or paste text directly
        </summary>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={8}
          placeholder="Paste notes, a chapter excerpt, or a scratch explanation."
          className="mt-3 w-full resize-none rounded-card border border-border bg-surface p-4 text-sm leading-relaxed text-text placeholder:text-faint focus:border-accent focus:outline-none"
        />
        <Button
          variant="primary"
          className="mt-3"
          disabled={!text.trim()}
          onClick={() => api.ingestText({ text }).then(() => setText(""))}
        >
          Add this
        </Button>
      </details>

      <section className="mt-10">
        <h2 className="text-sm font-medium text-dim">Recent</h2>
        {jobs.length === 0 ? (
          <div className="mt-3">
            <Empty title="Nothing ingested yet." />
          </div>
        ) : (
          <ul className="mt-3 space-y-2">
            {jobs.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function JobRow({ job }: { job: Job }) {
  const running = job.status === "queued" || job.status === "running";
  return (
    <li>
      <Card className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-text">
              {job.label || job.kind}
            </p>
            <p className="mt-0.5 text-xs text-faint">
              {job.error ? (
                <span className="text-wrong">{job.error}</span>
              ) : job.status === "succeeded" ? (
                <>
                  {job.result.questions ?? 0} questions from{" "}
                  {job.result.concepts ?? 0} concepts
                  {Number(job.result.duplicates ?? 0) > 0 &&
                    ` · ${job.result.duplicates} near-duplicates rejected`}
                </>
              ) : (
                job.detail || "Queued"
              )}
            </p>
          </div>
          <Pill
            tone={
              job.status === "succeeded"
                ? "accent"
                : job.status === "failed"
                  ? "wrong"
                  : "info"
            }
          >
            {job.status}
          </Pill>
        </div>
        {running && (
          <div className="mt-3">
            <Bar value={job.progress} tone="info" />
          </div>
        )}
      </Card>
    </li>
  );
}
