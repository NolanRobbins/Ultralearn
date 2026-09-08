"""The Ultralearn HTTP service.

A thin layer over the engine. It holds no learning logic of its own: the
scheduler, learner model, generation, and providers stay independent of any UI,
so the frontend can be replaced without touching them.

Anything that calls an LLM is enqueued as a job and reported over SSE rather
than handled in the request, so no screen ever waits on a provider.
"""

from __future__ import annotations

import asyncio
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
from ..config import AppConfig
from ..db import KnowledgeDB
from ..examiner import GradeResult, grade_answer
from ..jobs import JobWorker
from ..learner import build_session
from ..providers import Provider, ProviderError, build_provider
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
        )

    def update_settings(self, values: dict[str, str]) -> None:
        self._settings.update(values)


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
        ready, message = True, f"{provider.name} is ready."
        if not available:
            ready, message = False, f"{provider.name} is not available on this machine."
        elif hasattr(provider, "check_auth"):
            ready, message = provider.check_auth()
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
        )

    # ------------------------------------------------------------------
    # Study
    # ------------------------------------------------------------------

    @app.post("/api/session", response_model=SessionResponse)
    def start_session(size: int = 10, app_state: AppState = Guarded) -> SessionResponse:
        db = app_state.db
        items: list[QuestionOut] = []
        seen: set[int] = set()
        for candidate in build_session(db, limit=size):
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

    @app.get("/api/search", response_model=list[SearchHit])
    def search(q: str, app_state: AppState = Guarded) -> list[SearchHit]:
        return [
            SearchHit(
                kind=row["kind"],
                ref_id=int(row["ref_id"]),
                title=row["title"],
                snippet=str(row["snippet"])[:400],
            )
            for row in app_state.db.search(q)
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
            str(payload.get(key) or "").strip() for key in ("text", "url", "raw")
        )
        if not has_content:
            raise HTTPException(status_code=400, detail="Nothing to ingest.")
        job_id = app_state.db.enqueue_job(
            "ingest", payload, label=payload.get("title") or payload.get("url") or "Pasted text"
        )
        job = app_state.db.get_job(job_id)
        assert job is not None
        return JobOut(**job)

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

    @app.post("/api/settings")
    def settings(values: dict[str, str], app_state: AppState = Guarded) -> dict[str, str]:
        app_state.update_settings(values)
        return {"status": "ok"}

    _mount_frontend(app, state)
    return app


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
