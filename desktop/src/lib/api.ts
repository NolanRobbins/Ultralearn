/**
 * Typed client for the Ultralearn API.
 *
 * The token arrives as a `?token=` query parameter (the shell opens the window
 * with it) and is kept in sessionStorage so a reload inside the window does not
 * lose it. In development it can also come from VITE_ULTRALEARN_TOKEN.
 */

const TOKEN_KEY = "ultralearn.token";

function readToken(): string {
  const fromUrl = new URLSearchParams(window.location.search).get("token");
  if (fromUrl) {
    sessionStorage.setItem(TOKEN_KEY, fromUrl);
    // Keep the token out of the visible URL and out of any history entry.
    window.history.replaceState({}, "", window.location.pathname);
    return fromUrl;
  }
  return (
    sessionStorage.getItem(TOKEN_KEY) ??
    (import.meta.env.VITE_ULTRALEARN_TOKEN as string | undefined) ??
    ""
  );
}

export const token = readToken();

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Ultralearn-Token": token,
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* the body was not JSON; the status text will do */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Mode = "due" | "practice" | "drill";
export type Verdict = "correct" | "partial" | "incorrect";

export interface Health {
  provider: string;
  available: boolean;
  ready: boolean;
  message: string;
}

export interface Question {
  id: number;
  concept_id: number;
  concept_title: string;
  topic_slug: string;
  question_type: string;
  prompt: string;
  options: string[];
  bloom: string;
  written: boolean;
  mode: Mode;
  misconceptions: string[];
}

export interface Reveal {
  expected_answer: string;
  explanation: string;
  answer_index: number | null;
  answer_indices: number[];
}

export interface Grade {
  verdict: Verdict;
  score: number;
  missing: string[];
  misconception: string;
  probe: string;
  fix: string;
  expected_answer: string;
  explanation: string;
  graded_by: string;
}

export interface DayActivity {
  date: string;
  reviews: number;
  accuracy: number | null;
}

export interface Today {
  due: number;
  concepts: number;
  questions: number;
  sources: number;
  reviews: number;
  leeches: number;
  open_misconceptions: number;
  streak_days: number;
  reviewed_today: number;
  estimated_minutes: number;
  recent_days: DayActivity[];
  code_problems?: number;
  due_code?: number;
  math_formulas?: number;
  due_math?: number;
}

export interface Job {
  id: number;
  kind: string;
  label: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  detail: string;
  result: Record<string, number | string>;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Concept {
  id: number;
  title: string;
  topic_slug: string;
  mastery: number;
  due: string;
  leech: boolean;
  question_count: number;
  code_count?: number;
  math_count?: number;
}

export interface Source {
  id: number;
  type: string;
  title: string;
  author: string | null;
  chunk_count: number;
  created_at: string;
}

export interface SearchHit {
  kind: string;
  ref_id: number;
  title: string;
  snippet: string;
  via?: string;
  score?: number | null;
}

export interface Stats {
  totals: Record<string, number>;
  topic_mastery: Record<string, number>;
  calibration: Record<string, number>;
  weak_spots: Array<Record<string, string | number>>;
  misconceptions: Array<Record<string, string | number>>;
  activity: DayActivity[];
}

export interface CoachingReport {
  id: number;
  ts: string;
  provider: string;
  report: string;
}

export interface Settings {
  provider: string;
  providers: string[];
  claude_model: string;
  cursor_model?: string;
  cursor_models?: Array<{ id: string; label: string }>;
  cursor_key_configured?: boolean;
  db_path: string;
  timeout_seconds: number;
}

export interface ReviewPayload {
  concept_id: number;
  question_id: number;
  correct: boolean;
  confidence: number;
  latency_seconds?: number;
  answer_text?: string;
  mode?: Mode;
  score?: number | null;
  graded_by?: string;
  critique?: string;
  misconception?: string;
}

export interface CodeProblem {
  id: number;
  slug: string;
  title: string;
  prompt: string;
  starter: string;
  difficulty: string;
  tags: string[];
  concept_id: number | null;
  concept_title: string | null;
  timeout_seconds: number;
  attempts: number;
  ever_passed: boolean;
  last_passed: boolean | null;
  last_code: string | null;
}

export interface CodeRunResult {
  passed: boolean;
  checks: Array<{ name: string; ok: boolean; error: string }>;
  stdout: string;
  stderr: string;
  runtime_ms: number;
  timed_out: boolean;
  error: string;
}

export interface MathFormula {
  id: number;
  slug: string;
  title: string;
  latex: string;
  intuition: string;
  tags: string[];
  concept_id: number | null;
  concept_title: string | null;
  blanks: Array<{ id: string; prompt: string }>;
  terms: Array<{ symbol: string; name: string }>;
  attempts: number;
  ever_passed: boolean;
}

export interface MathGrade {
  passed: boolean;
  verdict: string;
  score: number;
  hits: string[];
  missing: string[];
  spoken: string;
  intuition: string;
  blank_results: Array<{ id?: string; ok?: boolean; answer?: string; why?: string }>;
  term_why: string;
  fix: string;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export const api = {
  health: () => request<Health>("/api/health"),
  today: () => request<Today>("/api/today"),
  stats: () => request<Stats>("/api/stats"),

  session: (size = 10) =>
    request<{ items: Question[]; total: number }>(`/api/session?size=${size}`, {
      method: "POST",
    }),
  drill: (size = 10) =>
    request<{ items: Question[]; total: number }>(`/api/session/drill?size=${size}`, {
      method: "POST",
    }),
  focus: (query: string, size = 10) =>
    request<{ items: Question[]; total: number }>(
      `/api/session/focus?q=${encodeURIComponent(query)}&size=${size}`,
      { method: "POST" },
    ),
  reveal: (questionId: number) => request<Reveal>(`/api/questions/${questionId}/reveal`),
  grade: (questionId: number, answer: string, confidence: number) =>
    request<Grade>("/api/grade", {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, answer, confidence }),
    }),
  review: (payload: ReviewPayload) =>
    request<{ mastery: number; due: string; leech: boolean; resolved_misconceptions: number }>(
      "/api/review",
      { method: "POST", body: JSON.stringify(payload) },
    ),

  concepts: () => request<Concept[]>("/api/concepts"),
  sources: () => request<Source[]>("/api/sources"),
  search: (q: string) => request<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}`),
  generateFromSource: (sourceId: number) =>
    request<Job>(`/api/sources/${sourceId}/generate`, { method: "POST" }),
  generateFromFocus: (query: string) =>
    request<Job>(`/api/focus/generate?q=${encodeURIComponent(query)}`, { method: "POST" }),

  coachingReports: () => request<CoachingReport[]>("/api/coaching"),
  requestCoaching: () => request<Job>("/api/coaching", { method: "POST" }),

  settings: () => request<Settings>("/api/settings"),
  saveSettings: (values: Record<string, string>) =>
    request<{ status: string }>("/api/settings", {
      method: "POST",
      body: JSON.stringify(values),
    }),

  jobs: () => request<Job[]>("/api/jobs"),
  ingestText: (body: { text?: string; url?: string; title?: string; generate?: boolean }) =>
    request<Job>("/api/ingest", { method: "POST", body: JSON.stringify(body) }),
  ingestFile: async (file: File): Promise<Job> => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch("/api/ingest", {
      method: "POST",
      headers: { "X-Ultralearn-Token": token },
      body: form,
    });
    if (!response.ok) {
      throw new ApiError(await response.text(), response.status);
    }
    return response.json();
  },

  codeProblems: (conceptId?: number) =>
    request<CodeProblem[]>(
      conceptId
        ? `/api/code/problems?concept_id=${conceptId}`
        : "/api/code/problems",
    ),
  codeProblem: (id: number) => request<CodeProblem>(`/api/code/problems/${id}`),
  runCode: (problemId: number, code: string) =>
    request<CodeRunResult>("/api/code/run", {
      method: "POST",
      body: JSON.stringify({ problem_id: problemId, code }),
    }),

  mathFormulas: (conceptId?: number) =>
    request<MathFormula[]>(
      conceptId
        ? `/api/math/formulas?concept_id=${conceptId}`
        : "/api/math/formulas",
    ),
  mathFormula: (id: number) => request<MathFormula>(`/api/math/formulas/${id}`),
  gradeMath: (body: {
    formula_id: number;
    mode: "speak" | "fill" | "why";
    spoken?: string;
    blanks?: Record<string, string>;
    term_symbol?: string;
    why?: string;
  }) =>
    request<MathGrade>("/api/math/grade", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generateMath: (opts: { conceptId?: number; query?: string }) => {
    const params = new URLSearchParams();
    if (opts.conceptId) params.set("concept_id", String(opts.conceptId));
    if (opts.query) params.set("q", opts.query);
    const query = params.toString();
    return request<Job>(`/api/math/generate${query ? `?${query}` : ""}`, {
      method: "POST",
    });
  },
};

/** Subscribe to live job progress. Returns an unsubscribe function. */
export function subscribeToJobs(onJobs: (jobs: Job[]) => void): () => void {
  const source = new EventSource(
    `/api/jobs/stream/events?token=${encodeURIComponent(token)}`,
  );
  source.addEventListener("jobs", (event) => {
    try {
      onJobs(JSON.parse((event as MessageEvent).data));
    } catch {
      /* a malformed frame should not tear down the stream */
    }
  });
  return () => source.close();
}
