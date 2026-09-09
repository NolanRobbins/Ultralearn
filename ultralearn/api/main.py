"""The Ultralearn HTTP service.

A thin layer over the engine. It holds no learning logic of its own: the
scheduler, learner model, generation, and providers stay independent of any UI,
so the frontend can be replaced without touching them.

Anything that calls an LLM is enqueued as a job and reported over SSE rather
than handled in the request, so no screen ever waits on a provider.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .. import ingest as ingest_jobs  # noqa: F401  (registers job handlers)
from .. import math_gen as math_jobs  # noqa: F401
from ..math_grader import answers_match, grade_phrases, why_phrases
from ..code_runner import run_solution
from ..config import AppConfig, local_secret_configured, persist_local_secret
from ..db import KnowledgeDB
from ..examiner import GradeResult, grade_answer
from ..jobs import JobWorker
from ..learner import build_focus_session, build_session
from ..providers import CURSOR_MODELS, Provider, ProviderError, build_provider
from ..scheduler import derive_quality
from .schemas import (
    ConceptOut,
    GradeRequest,
    GradeResponse,
    HealthResponse,
    IngestRequest,
    JobOut,
    QuestionOut,
    RevealResponse,
    ReviewRequest,
    ReviewResponse,
    SearchHit,
    SessionResponse,
    SourceOut,
    TodayResponse,
    CodeCheckOut,
    CodeProblemOut,
    CodeRunRequest,
    CodeRunResponse,
    MathFormulaOut,
    MathGradeRequest,
    MathGradeResponse,
)

#: Formats where the learner produces the answer instead of recognising it.
#: Free recall is the default; multiple choice is the warmup.
WRITTEN_FORMATS = {"cloze", "spot_error", "short_answer", "compare_contrast"}

#: Rough pace used to estimate session length on the Today screen.
SECONDS_PER_QUESTION = 45


class AppState:
    """Process-wide singletons, created once at startup."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.token = secrets.token_urlsafe(24)
        self.db = KnowledgeDB(config.db_path)
        self.db.initialize()
        self.worker = JobWorker(self.db, self.build_provider)
        self._settings: dict[str, str] = {}

    def build_provider(self) -> Provider:
        return build_provider(
            self._settings.get("provider", self.config.provider),
            self.config,
            anthropic_key=self._settings.get("anthropic_key", ""),
            openai_key=self._settings.get("openai_key", ""),
            cursor_key=self._settings.get("cursor_key", ""),
            cursor_model=self._settings.get("cursor_model", self.config.cursor_model),
        )

    def update_settings(self, values: dict[str, str]) -> None:
        # Empty secrets must not wipe a key that is already in memory or the env.
        cleaned = {
            key: value
            for key, value in values.items()
            if not (key.endswith("_key") and not str(value).strip())
        }
        self._settings.update(cleaned)

    def setting(self, key: str, default: str = "") -> str:
        return self._settings.get(key, default)


def create_app(config: AppConfig | None = None) -> FastAPI:
    state = AppState(config or AppConfig.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.worker.start()
        try:
            yield
        finally:
            state.worker.stop()

    app = FastAPI(title="Ultralearn", version="0.2.0", lifespan=lifespan)
    app.state.ultralearn = state

    # The dev frontend runs on its own Vite port; the packaged app is same-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_token(x_ultralearn_token: str = Header(default="")) -> AppState:
        """Guard the API against other local processes.

        The server binds to loopback, but any process on the machine can reach
        loopback. A per-launch token means only the window we opened can drive it.
        """

        if not secrets.compare_digest(x_ultralearn_token, state.token):
            raise HTTPException(status_code=401, detail="Invalid or missing API token.")
        return state

    Guarded = Depends(require_token)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @app.get("/api/health", response_model=HealthResponse)
    def health(app_state: AppState = Guarded) -> HealthResponse:
        provider = app_state.build_provider()
        available = provider.available()
        if hasattr(provider, "check_auth"):
            ready, message = provider.check_auth()
        elif not available:
            ready, message = False, f"{provider.name} is not available on this machine."
        else:
            ready, message = True, f"{provider.name} is ready."
        return HealthResponse(
            provider=provider.name, available=available, ready=ready, message=message
        )

    @app.get("/api/today", response_model=TodayResponse)
    def today(app_state: AppState = Guarded) -> TodayResponse:
        db = app_state.db
        stats = db.stats()
        due = int(stats["due"])
        return TodayResponse(
            due=due,
            concepts=int(stats["concepts"]),
            questions=int(stats["questions"]),
            sources=int(stats["sources"]),
            reviews=int(stats["reviews"]),
            leeches=int(stats["leeches"]),
            open_misconceptions=len(db.open_misconceptions(limit=500)),
            streak_days=db.streak_days(),
            reviewed_today=db.reviewed_today(),
            estimated_minutes=max(1, round(min(due, 10) * SECONDS_PER_QUESTION / 60)),
            recent_days=db.daily_activity(30),
            code_problems=int(stats.get("code_problems") or 0),
            due_code=db.due_code_problem_count(),
            math_formulas=int(stats.get("math_formulas") or 0),
            due_math=db.due_math_formula_count(),
        )

    # ------------------------------------------------------------------
    # Study
    # ------------------------------------------------------------------

    @app.post("/api/session", response_model=SessionResponse)
    def start_session(size: int = 10, app_state: AppState = Guarded) -> SessionResponse:
        return _session_from_candidates(app_state.db, build_session(app_state.db, limit=size), size)

    @app.post("/api/session/drill", response_model=SessionResponse)
    def start_drill(size: int = 10, app_state: AppState = Guarded) -> SessionResponse:
        """A round built purely from unresolved misconceptions and leeches."""

        db = app_state.db
        items: list[QuestionOut] = []
        seen: set[int] = set()
        for row in db.open_misconceptions(limit=size * 2):
            concept = db.get_concept(int(row["concept_id"]))
            if concept is None:
                continue
            question = db.get_question_for_concept(concept.id)
            if question is None or question.id in seen:
                continue
            seen.add(question.id)
            items.append(_question_out(db, question, concept, mode="drill"))
            if len(items) >= size:
                break
        return SessionResponse(items=items, total=len(items))

    @app.post("/api/session/focus", response_model=SessionResponse)
    def start_focus(q: str, size: int = 10, app_state: AppState = Guarded) -> SessionResponse:
        """A round on whatever the learner asked to work on today."""

        query = q.strip()
        if not query:
            raise HTTPException(status_code=400, detail="Say what you want to work on.")
        return _session_from_candidates(
            app_state.db, build_focus_session(app_state.db, query, limit=size), size
        )

    @app.get("/api/questions/{question_id}/reveal", response_model=RevealResponse)
    def reveal(question_id: int, app_state: AppState = Guarded) -> RevealResponse:
        question = app_state.db.get_question(question_id)
        if question is None:
            raise HTTPException(status_code=404, detail="No such question.")
        return RevealResponse(
            expected_answer=_expected_answer(question),
            explanation=question.explanation,
            answer_index=question.answer.get("index"),
            answer_indices=list(question.answer.get("indices", [])),
        )

    @app.post("/api/grade", response_model=GradeResponse)
    def grade(request: GradeRequest, app_state: AppState = Guarded) -> GradeResponse:
        """Grade a written answer.

        Synchronous on purpose: the learner is sitting in front of it waiting, and
        a single critique is one short call rather than a batch.
        """

        question = app_state.db.get_question(request.question_id)
        if question is None:
            raise HTTPException(status_code=404, detail="No such question.")
        expected = _expected_answer(question)
        try:
            result = grade_answer(
                app_state.build_provider(), question.prompt, expected, request.answer
            )
        except ProviderError as exc:
            result = GradeResult.unavailable(str(exc))
        return GradeResponse(
            verdict=result.verdict,
            score=result.score,
            missing=result.missing,
            misconception=result.misconception,
            probe=result.probe,
            fix=result.fix,
            expected_answer=expected,
            explanation=question.explanation,
            graded_by=result.graded_by,
        )

    @app.post("/api/review", response_model=ReviewResponse)
    def review(request: ReviewRequest, app_state: AppState = Guarded) -> ReviewResponse:
        db = app_state.db
        quality = derive_quality(request.correct, request.confidence)
        db.record_review(
            concept_id=request.concept_id,
            question_id=request.question_id,
            correct=request.correct,
            confidence=request.confidence,
            quality=quality,
            latency_seconds=request.latency_seconds,
            answer_text=request.answer_text,
            critique=request.critique,
            provider=app_state.build_provider().name,
            update_schedule=request.mode == "due",
            mode=request.mode,
            score=request.score,
            graded_by=request.graded_by,
        )
        if request.misconception:
            db.record_misconception(request.concept_id, request.misconception)
        # A clean, confident answer retires what was previously misunderstood.
        resolved = 0
        if request.correct and not request.misconception:
            resolved = db.resolve_misconceptions(request.concept_id)

        concept = db.get_concept(request.concept_id)
        if concept is None:
            raise HTTPException(status_code=404, detail="No such concept.")
        return ReviewResponse(
            concept_id=concept.id,
            mastery=concept.mastery,
            due=concept.due,
            leech=concept.leech,
            resolved_misconceptions=resolved,
        )

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    @app.get("/api/concepts", response_model=list[ConceptOut])
    def concepts(app_state: AppState = Guarded) -> list[ConceptOut]:
        return [
            ConceptOut(
                id=int(row["id"]),
                title=row["title"],
                topic_slug=row["topic_slug"],
                mastery=float(row["mastery"]),
                due=row["due"],
                leech=bool(row["leech"]),
                question_count=int(row["question_count"]),
                code_count=int(row["code_count"] or 0),
                math_count=int(row["math_count"] or 0) if "math_count" in row.keys() else 0,
            )
            for row in app_state.db.list_concepts()
        ]

    @app.get("/api/sources", response_model=list[SourceOut])
    def sources(app_state: AppState = Guarded) -> list[SourceOut]:
        return [
            SourceOut(
                id=int(row["id"]),
                type=row["type"],
                title=row["title"],
                author=row["author"],
                chunk_count=int(row["chunk_count"]),
                created_at=row["created_at"],
            )
            for row in app_state.db.list_sources()
        ]

    def _code_problem_out(row: Any) -> CodeProblemOut:
        keys = set(row.keys())
        tags_raw = row["tags_json"] if "tags_json" in keys else "[]"
        try:
            tags = [str(item) for item in json.loads(tags_raw or "[]")]
        except json.JSONDecodeError:
            tags = []
        last_passed = row["last_passed"] if "last_passed" in keys else None
        return CodeProblemOut(
            id=int(row["id"]),
            slug=row["slug"],
            title=row["title"],
            prompt=row["prompt"],
            starter=row["starter"],
            difficulty=row["difficulty"],
            tags=tags,
            concept_id=int(row["concept_id"]) if row["concept_id"] is not None else None,
            concept_title=row["concept_title"] if "concept_title" in keys else None,
            timeout_seconds=int(row["timeout_seconds"]),
            attempts=int(row["attempts"] or 0) if "attempts" in keys else 0,
            ever_passed=bool(row["ever_passed"]) if "ever_passed" in keys else False,
            last_passed=None if last_passed is None else bool(last_passed),
            last_code=row["last_code"] if "last_code" in keys else None,
        )

    @app.get("/api/code/problems", response_model=list[CodeProblemOut])
    def code_problems(concept_id: int | None = None, app_state: AppState = Guarded) -> list[CodeProblemOut]:
        return [_code_problem_out(row) for row in app_state.db.list_code_problems(concept_id)]

    @app.get("/api/code/problems/{problem_id}", response_model=CodeProblemOut)
    def code_problem(problem_id: int, app_state: AppState = Guarded) -> CodeProblemOut:
        found = app_state.db.get_code_problem(problem_id)
        if found is None:
            raise HTTPException(status_code=404, detail="No such problem.")
        listed = next(
            (row for row in app_state.db.list_code_problems() if int(row["id"]) == problem_id),
            None,
        )
        return _code_problem_out(listed or found)

    @app.post("/api/code/run", response_model=CodeRunResponse)
    def run_code(request: CodeRunRequest, app_state: AppState = Guarded) -> CodeRunResponse:
        problem = app_state.db.get_code_problem(request.problem_id, include_tests=True)
        if problem is None:
            raise HTTPException(status_code=404, detail="No such problem.")
        result = run_solution(
            request.code,
            problem["tests"],
            timeout_seconds=float(problem["timeout_seconds"] or 8),
        )
        output = result.error or result.stderr or result.stdout
        app_state.db.record_code_attempt(
            request.problem_id,
            request.code,
            result.passed,
            result.passed_count,
            result.failed_count,
            result.runtime_ms,
            output,
        )
        return CodeRunResponse(
            passed=result.passed,
            checks=[CodeCheckOut(name=item.name, ok=item.ok, error=item.error) for item in result.checks],
            stdout=result.stdout,
            stderr=result.stderr,
            runtime_ms=result.runtime_ms,
            timed_out=result.timed_out,
            error=result.error,
        )

    def _math_formula_out(row: Any) -> MathFormulaOut:
        keys = set(row.keys())
        try:
            tags = [str(item) for item in json.loads(row["tags_json"] or "[]")]
        except json.JSONDecodeError:
            tags = []
        try:
            blanks_raw = json.loads(row["blanks_json"] or "[]") if "blanks_json" in keys else []
        except json.JSONDecodeError:
            blanks_raw = []
        try:
            terms_raw = json.loads(row["terms_json"] or "[]") if "terms_json" in keys else []
        except json.JSONDecodeError:
            terms_raw = []
        return MathFormulaOut(
            id=int(row["id"]),
            slug=row["slug"],
            title=row["title"],
            latex=row["latex"],
            intuition="",
            tags=tags,
            concept_id=int(row["concept_id"]) if row["concept_id"] is not None else None,
            concept_title=row["concept_title"] if "concept_title" in keys else None,
            blanks=[{"id": str(item.get("id") or ""), "prompt": str(item.get("prompt") or "")} for item in blanks_raw],
            terms=[
                {"symbol": str(item.get("symbol") or ""), "name": str(item.get("name") or "")}
                for item in terms_raw
            ],
            attempts=int(row["attempts"] or 0) if "attempts" in keys else 0,
            ever_passed=bool(row["ever_passed"]) if "ever_passed" in keys else False,
        )

    @app.get("/api/math/formulas", response_model=list[MathFormulaOut])
    def math_formulas(concept_id: int | None = None, app_state: AppState = Guarded) -> list[MathFormulaOut]:
        return [_math_formula_out(row) for row in app_state.db.list_math_formulas(concept_id)]

    @app.get("/api/math/formulas/{formula_id}", response_model=MathFormulaOut)
    def math_formula(formula_id: int, app_state: AppState = Guarded) -> MathFormulaOut:
        found = app_state.db.get_math_formula(formula_id)
        if found is None:
            raise HTTPException(status_code=404, detail="No such formula.")
        listed = next(
            (row for row in app_state.db.list_math_formulas() if int(row["id"]) == formula_id),
            None,
        )
        return _math_formula_out(listed or found)

    @app.post("/api/math/grade", response_model=MathGradeResponse)
    def grade_math(request: MathGradeRequest, app_state: AppState = Guarded) -> MathGradeResponse:
        formula = app_state.db.get_math_formula(request.formula_id, include_answers=True)
        if formula is None:
            raise HTTPException(status_code=404, detail="No such formula.")
        blanks = json.loads(formula["blanks_json"] or "[]")
        terms = json.loads(formula["terms_json"] or "[]")
        phrases = json.loads(formula["key_phrases_json"] or "[]")
        response: MathGradeResponse
        if request.mode == "speak":
            grade = grade_phrases(request.spoken, [str(item) for item in phrases])
            fix = ""
            if grade.missing:
                fix = "Name these pieces of the mechanism: " + ", ".join(grade.missing) + "."
            response = MathGradeResponse(
                passed=grade.passed,
                verdict=grade.verdict,
                score=grade.score,
                hits=grade.hits,
                missing=grade.missing,
                spoken=formula["spoken"],
                intuition=formula["intuition"],
                fix=fix,
            )
        elif request.mode == "fill":
            submitted = {
                str(key): value
                for key, value in request.blanks.items()
                if str(value).strip()
            }
            targets = [blank for blank in blanks if str(blank.get("id") or "") in submitted]
            if not targets:
                targets = list(blanks)
            results = []
            all_ok = True
            for blank in targets:
                given = submitted.get(str(blank.get("id") or ""), "")
                ok = answers_match(
                    given,
                    str(blank.get("answer") or ""),
                    list(blank.get("aliases") or []),
                )
                all_ok = all_ok and ok
                results.append(
                    {
                        "id": blank.get("id"),
                        "ok": ok,
                        "answer": blank.get("answer"),
                        "why": blank.get("why") or "",
                    }
                )
            response = MathGradeResponse(
                passed=all_ok and bool(results),
                verdict="correct" if all_ok and results else "incorrect",
                score=sum(1 for item in results if item["ok"]) / max(1, len(results)),
                blank_results=results,
                intuition=formula["intuition"],
                spoken=formula["spoken"],
            )
        else:
            term = next(
                (
                    item
                    for item in terms
                    if str(item.get("symbol") or "") == request.term_symbol
                    or str(item.get("name") or "") == request.term_symbol
                ),
                terms[0] if terms else {},
            )
            why_gold = str(term.get("why") or "")
            grade = grade_phrases(request.why, why_phrases(why_gold), threshold=0.5)
            response = MathGradeResponse(
                passed=grade.passed,
                verdict=grade.verdict,
                score=grade.score,
                hits=grade.hits,
                missing=grade.missing,
                term_why=why_gold,
                intuition=formula["intuition"],
                spoken=formula["spoken"],
                fix="" if grade.passed else "Say what would break if this term were missing.",
            )
        app_state.db.record_math_attempt(
            request.formula_id,
            request.mode,
            response.passed,
            {
                "spoken": request.spoken,
                "blanks": request.blanks,
                "term_symbol": request.term_symbol,
                "why": request.why,
            },
            response.model_dump(),
        )
        return response

    @app.post("/api/math/generate", response_model=JobOut)
    def generate_math(concept_id: int | None = None, q: str = "", app_state: AppState = Guarded) -> JobOut:
        payload: dict[str, Any] = {}
        if concept_id:
            payload["concept_id"] = concept_id
        if q.strip():
            payload["query"] = q.strip()
        if not payload:
            raise HTTPException(status_code=400, detail="Pick a concept or describe the formula.")
        job_id = app_state.db.enqueue_job(
            "generate_math",
            payload,
            label=f"Formula · {q.strip() or 'concept'}",
        )
        found = app_state.db.get_job(job_id)
        assert found is not None
        return JobOut(**found)

    @app.get("/api/search", response_model=list[SearchHit])
    def search(q: str, app_state: AppState = Guarded) -> list[SearchHit]:
        return [
            SearchHit(
                kind=hit["kind"],
                ref_id=int(hit["ref_id"]),
                title=hit["title"],
                snippet=str(hit["snippet"])[:400],
                via=hit.get("via", "text"),
                score=hit.get("score"),
            )
            for hit in app_state.db.unified_search(q)
        ]

    @app.get("/api/stats")
    def stats(app_state: AppState = Guarded) -> dict[str, Any]:
        db = app_state.db
        return {
            "totals": dict(db.stats()),
            "topic_mastery": db.topic_mastery(),
            "calibration": db.calibration(),
            "weak_spots": [dict(row) for row in db.weak_spots()],
            "misconceptions": [dict(row) for row in db.open_misconceptions(limit=25)],
            "activity": db.daily_activity(60),
        }

    # ------------------------------------------------------------------
    # Ingestion and jobs
    # ------------------------------------------------------------------

    @app.post("/api/ingest", response_model=JobOut)
    async def ingest(request: Request, app_state: AppState = Guarded) -> JobOut:
        """Accept dropped material. One call, no forms, returns immediately."""

        payload = await _ingest_payload(request)
        has_content = any(
            str(payload.get(key) or "").strip() for key in ("text", "url", "raw", "folder")
        )
        if not has_content:
            raise HTTPException(status_code=400, detail="Nothing to ingest.")
        if payload.get("folder"):
            job_id = app_state.db.enqueue_job(
                "ingest_folder", payload, label=payload.get("title") or Path(payload["folder"]).name
            )
        else:
            job_id = app_state.db.enqueue_job(
                "ingest", payload, label=payload.get("title") or payload.get("url") or "Pasted text"
            )
        job = app_state.db.get_job(job_id)
        assert job is not None
        return JobOut(**job)

    @app.post("/api/sources/{source_id}/generate", response_model=JobOut)
    def generate_from_source(source_id: int, app_state: AppState = Guarded) -> JobOut:
        sources = {int(row["id"]): row for row in app_state.db.list_sources()}
        source = sources.get(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="No such source.")
        job_id = app_state.db.enqueue_job(
            "generate",
            {"source_id": source_id, "title": source["title"]},
            label=f"More questions · {source['title']}",
        )
        found = app_state.db.get_job(job_id)
        assert found is not None
        return JobOut(**found)

    @app.post("/api/focus/generate", response_model=JobOut)
    def generate_from_focus(q: str, app_state: AppState = Guarded) -> JobOut:
        query = q.strip()
        if not query:
            raise HTTPException(status_code=400, detail="Say what you want questions on.")
        job_id = app_state.db.enqueue_job(
            "generate_focus", {"query": query}, label=f"Focus · {query}"
        )
        found = app_state.db.get_job(job_id)
        assert found is not None
        return JobOut(**found)

    @app.get("/api/jobs", response_model=list[JobOut])
    def jobs(active_only: bool = False, app_state: AppState = Guarded) -> list[JobOut]:
        return [JobOut(**job) for job in app_state.db.list_jobs(active_only=active_only)]

    @app.get("/api/jobs/{job_id}", response_model=JobOut)
    def job(job_id: int, app_state: AppState = Guarded) -> JobOut:
        found = app_state.db.get_job(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="No such job.")
        return JobOut(**found)

    @app.get("/api/jobs/stream/events")
    async def job_events(token: str = "") -> EventSourceResponse:
        """Live job progress.

        EventSource cannot set headers, so the token arrives as a query parameter
        here rather than in ``X-Ultralearn-Token``.
        """

        if not secrets.compare_digest(token, state.token):
            raise HTTPException(status_code=401, detail="Invalid or missing API token.")

        async def publish():
            previous: str | None = None
            while True:
                active = state.db.list_jobs(limit=10)
                snapshot = repr(active)
                if snapshot != previous:
                    previous = snapshot
                    yield {"event": "jobs", "data": _json(active)}
                await asyncio.sleep(0.6)

        return EventSourceResponse(publish())

    @app.post("/api/coaching", response_model=JobOut)
    def request_coaching(app_state: AppState = Guarded) -> JobOut:
        job_id = app_state.db.enqueue_job("coaching", {}, label="Diagnostic report")
        found = app_state.db.get_job(job_id)
        assert found is not None
        return JobOut(**found)

    @app.get("/api/coaching")
    def coaching_reports(app_state: AppState = Guarded) -> list[dict[str, Any]]:
        return [dict(row) for row in app_state.db.recent_coaching_reports(limit=10)]

    @app.get("/api/settings")
    def read_settings(app_state: AppState = Guarded) -> dict[str, Any]:
        config = app_state.config
        return {
            "provider": app_state.setting("provider", config.provider),
            "providers": ["claude_code", "cursor", "anthropic", "openai", "ollama", "manual"],
            "claude_model": config.claude_model,
            "cursor_model": app_state.setting("cursor_model", config.cursor_model),
            "cursor_models": [{"id": model_id, "label": label} for model_id, label in CURSOR_MODELS],
            "cursor_key_configured": bool(
                app_state.setting("cursor_key") or local_secret_configured("CURSOR_API_KEY")
            ),
            "db_path": str(config.db_path),
            "timeout_seconds": config.provider_timeout_seconds,
        }

    @app.post("/api/settings")
    def settings(values: dict[str, str], app_state: AppState = Guarded) -> dict[str, str]:
        app_state.update_settings(values)
        key = str(values.get("cursor_key") or "").strip()
        if key:
            persist_local_secret("CURSOR_API_KEY", key)
        provider = str(values.get("provider") or "").strip()
        if provider:
            persist_local_secret("ULTRALEARN_PROVIDER", provider)
        cursor_model = str(values.get("cursor_model") or "").strip()
        if cursor_model:
            persist_local_secret("ULTRALEARN_CURSOR_MODEL", cursor_model)
        return {"status": "ok"}

    _mount_frontend(app, state)
    return app


def _session_from_candidates(db: KnowledgeDB, candidates: Any, size: int) -> SessionResponse:
    items: list[QuestionOut] = []
    seen: set[int] = set()
    for candidate in candidates:
        question = db.get_question_for_concept(candidate.concept.id)
        if question is None or question.id in seen:
            continue
        seen.add(question.id)
        items.append(
            _question_out(
                db,
                question,
                candidate.concept,
                mode="practice" if candidate.practice else "due",
            )
        )
        if len(items) >= size:
            break
    return SessionResponse(items=items, total=len(items))


def _question_out(db: KnowledgeDB, question: Any, concept: Any, mode: str) -> QuestionOut:
    return QuestionOut(
        id=question.id,
        concept_id=concept.id,
        concept_title=concept.title,
        topic_slug=concept.topic_slug,
        question_type=question.question_type,
        prompt=question.prompt,
        options=question.options,
        bloom=question.bloom,
        written=question.question_type in WRITTEN_FORMATS or not question.options,
        mode=mode,
        misconceptions=[row["statement"] for row in db.open_misconceptions(concept.id, limit=5)],
    )


def _expected_answer(question: Any) -> str:
    answer = question.answer
    if "text" in answer:
        return str(answer["text"])
    if "index" in answer and question.options:
        index = int(answer["index"])
        if 0 <= index < len(question.options):
            return question.options[index]
    if "indices" in answer and question.options:
        return "; ".join(
            question.options[i] for i in answer["indices"] if 0 <= i < len(question.options)
        )
    return ""


async def _ingest_payload(request: Request) -> dict[str, Any]:
    """Read an ingest request as either a file upload or a JSON body."""

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=400, detail="No file in upload.")
        data = await upload.read()  # type: ignore[union-attr]
        return {
            "filename": getattr(upload, "filename", "upload"),
            "raw": data.hex(),
            "title": str(form.get("title", "")),
            "topic_slug": str(form.get("topic_slug", "")),
            "generate": str(form.get("generate", "true")).lower() != "false",
        }
    body = IngestRequest(**(await request.json()))
    return body.model_dump()


def _json(value: Any) -> str:
    import json

    return json.dumps(value)


def _mount_frontend(app: FastAPI, state: AppState) -> None:
    """Serve the built frontend when it exists.

    Absent in development, where Vite serves the UI on its own port.
    """

    dist = Path(__file__).resolve().parent.parent.parent / "desktop" / "dist"
    if not dist.is_dir():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        candidate = dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
