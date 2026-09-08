"""Streamlit UI for Ultralearn.

The learning logic lives in the package modules so this UI can be replaced later
without rewriting the scheduler, data model, or providers.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import date
from typing import Any

import streamlit as st

from ultralearn.config import AppConfig
from ultralearn.db import KnowledgeDB
from ultralearn.generation import (
    DEFAULT_QUIZ_SIZE,
    generate_fresh_variant,
    generate_questions_batched,
    save_generated_questions,
)
from ultralearn.learner import build_session
from ultralearn.loaders import PDFTextExtractionError, extract_pdf_text
from ultralearn.models import Question
from ultralearn.providers import Provider, ProviderError, build_provider
from ultralearn.scheduler import derive_quality


SOURCE_TYPES = ["book", "paper", "chapter", "note", "lecture", "manual"]
QUESTION_TYPES = [
    "single_mcq",
    "multi_select",
    "cloze",
    "spot_error",
    "short_answer",
    "compare_contrast",
    "applied_scenario",
]
BLOOM_LEVELS = ["recall", "apply", "analyze"]
QUIZ_SIZE = DEFAULT_QUIZ_SIZE
CONFIDENCE_LABELS = {1: "1 · guessing", 2: "2 · shaky", 3: "3 · decent", 4: "4 · sure", 5: "5 · certain"}


def option_letter(index: int) -> str:
    """0 -> A, 1 -> B, ... for displaying answer choices."""

    return chr(ord("A") + index)


def main() -> None:
    st.set_page_config(page_title="Ultralearn", layout="wide")
    apply_theme()

    config = session_config()
    db = KnowledgeDB(config.db_path)
    db.initialize()
    provider = active_provider(config)
    provider_available = provider.available()

    with st.sidebar:
        st.title("Ultralearn")
        st.caption("Retrieval · retention · drill · feedback")
        page = st.radio(
            "Go to",
            ["Study", "Ingest", "Library", "Dashboard", "Coaching", "Settings"],
            label_visibility="collapsed",
        )
        st.divider()
        stats = db.stats()
        st.metric("Due concepts", stats["due"])
        st.metric("Concepts", stats["concepts"])
        st.metric("Questions", stats["questions"])
        st.metric("Leeches", stats["leeches"])
        st.divider()
        status = "ready" if provider_available else "not available"
        st.caption(f"Provider: {provider.name} · {status}")
        render_usage_summary()

    if page == "Study":
        study_page(db, provider, provider_available)
    elif page == "Ingest":
        ingest_page(db, provider, provider_available)
    elif page == "Library":
        library_page(db)
    elif page == "Dashboard":
        dashboard_page(db)
    elif page == "Coaching":
        coaching_page(db, provider, provider_available)
    else:
        settings_page(config, provider_available)


def session_config() -> AppConfig:
    env = AppConfig.from_env()
    if "provider" not in st.session_state:
        st.session_state.provider = env.provider
    if "model" not in st.session_state:
        st.session_state.model = env.model
    if "claude_command" not in st.session_state:
        st.session_state.claude_command = env.claude_command
    if "ollama_url" not in st.session_state:
        st.session_state.ollama_url = env.ollama_url
    if "ollama_model" not in st.session_state:
        st.session_state.ollama_model = env.ollama_model
    if "provider_timeout" not in st.session_state:
        st.session_state.provider_timeout = env.provider_timeout_seconds
    return replace(
        env,
        provider=st.session_state.provider,
        model=st.session_state.model,
        claude_command=st.session_state.claude_command,
        ollama_url=st.session_state.ollama_url,
        ollama_model=st.session_state.ollama_model,
        provider_timeout_seconds=int(st.session_state.provider_timeout),
    )


def active_provider(config: AppConfig) -> Provider:
    return build_provider(
        st.session_state.get("provider", config.provider),
        config,
        anthropic_key=st.session_state.get("anthropic_key", ""),
        openai_key=st.session_state.get("openai_key", ""),
    )


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------


def track_usage(provider: Provider) -> None:
    """Store the provider's last call usage so the sidebar shows a running total."""

    usage = getattr(provider, "last_usage", None)
    if usage:
        st.session_state.setdefault("usage_log", []).append(dict(usage))
        provider.last_usage = None


def render_usage_summary() -> None:
    usage_log: list[dict[str, Any]] = st.session_state.get("usage_log", [])
    if not usage_log:
        st.caption("LLM usage this session: none yet")
        return
    calls = len(usage_log)
    seconds = sum((entry.get("duration_ms") or 0) for entry in usage_log) / 1000
    cost = sum(entry.get("cost_usd") or 0.0 for entry in usage_log)
    tokens = sum((entry.get("input_tokens") or 0) + (entry.get("output_tokens") or 0) for entry in usage_log)
    line = f"LLM usage this session: {calls} calls · {seconds:.0f}s"
    if tokens:
        line += f" · {tokens:,} tokens"
    if cost:
        line += f" · ${cost:.4f}"
    st.caption(line)


def usage_blurb(usage: dict[str, Any] | None) -> str:
    if not usage:
        return ""
    parts = []
    if usage.get("duration_ms"):
        parts.append(f"{usage['duration_ms'] / 1000:.0f}s")
    if usage.get("output_tokens"):
        parts.append(f"{usage['output_tokens']} out tokens")
    if usage.get("cost_usd"):
        parts.append(f"${usage['cost_usd']:.4f}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Study: 10-question quiz rounds
# ---------------------------------------------------------------------------


def study_page(db: KnowledgeDB, provider: Provider, provider_available: bool) -> None:
    st.header("Study")

    if "quiz_items" not in st.session_state:
        quiz_landing(db, provider, provider_available)
        return

    items: list[dict[str, Any]] = st.session_state.quiz_items
    index: int = st.session_state.quiz_index
    if index >= len(items):
        quiz_summary(db)
        return

    render_quiz_question(db, provider, provider_available, items, index)


def quiz_landing(db: KnowledgeDB, provider: Provider, provider_available: bool) -> None:
    stats = db.stats()
    st.subheader("Ready for a round?")
    if stats["due"]:
        st.write(
            f"**{stats['due']}** concepts are due, out of {stats['concepts']} tracked. "
            f"Each round is {QUIZ_SIZE} questions blending due reviews, weak spots, and leeches."
        )
    else:
        st.write(
            f"Nothing is scheduled right now, but you can always practice: rounds fill with your "
            f"weakest of the {stats['concepts']} tracked concepts. Practice attempts count toward "
            f"mastery without stretching the review schedule."
        )
    fresh_default = st.session_state.get("quiz_fresh", provider_available)
    st.session_state.quiz_fresh = st.toggle(
        "Generate fresh question variants during the quiz",
        value=fresh_default,
        disabled=not provider_available,
        help="When a concept's question has been seen before, the provider writes a new variant on the "
        "spot so you can't pattern-match. Adds a short wait per repeated question.",
    )
    if st.button(f"Take the quiz ({QUIZ_SIZE} questions)", type="primary"):
        started = start_quiz(db)
        if started:
            st.rerun()
        else:
            st.info("No concepts with questions exist yet. Ingest material or add a manual question to start.")

    st.divider()
    focus_section(db, provider, provider_available)


def focus_section(db: KnowledgeDB, provider: Provider, provider_available: bool) -> None:
    """Semantic search over the whole library to drive a focused session."""

    st.subheader("Focus")
    query = st.text_input(
        "What do you want to study today?",
        key="focus_query",
        placeholder="e.g. sensor fusion failure modes, pot odds vs implied odds, backprop through time",
    )
    if not query.strip():
        st.caption(
            "Describe a topic in your own words. Ultralearn searches every source semantically — "
            "concepts and passages that are close in meaning surface together, even across overlapping sources."
        )
        return

    concept_matches = [(c, s) for c, s in db.semantic_concepts(query, k=8) if s > 0.05]
    chunk_matches = [c for c in db.semantic_chunks(query, k=4) if c["score"] > 0.05]
    if not concept_matches and not chunk_matches:
        st.info("No related material found yet. Ingest something on this topic first.")
        return

    today = date.today().isoformat()
    if concept_matches:
        st.markdown("**Matching concepts**")
        for concept, score in concept_matches:
            status = "due" if concept.due <= today else "practice"
            st.markdown(
                f"- {concept.title} — `{concept.topic_slug}` · mastery {concept.mastery * 100:.0f}% "
                f"· {status} · match {score:.2f}"
            )
    if chunk_matches:
        st.markdown("**Matching passages**")
        for chunk in chunk_matches:
            with st.expander(f"{chunk['source_title']} ({chunk['source_type']}) · match {chunk['score']:.2f}"):
                st.caption(chunk["text"][:700])

    col_round, col_generate = st.columns(2)
    if concept_matches and col_round.button("Start focused round", type="primary", use_container_width=True):
        if start_focused_quiz(db, [concept for concept, _ in concept_matches]):
            st.rerun()
        else:
            st.info("The matching concepts have no stored questions yet. Generate some first.")
    if chunk_matches and col_generate.button(
        f"Generate {QUIZ_SIZE} new questions about this", use_container_width=True
    ):
        if not provider_available:
            st.error(f"{provider.name} is not available.")
        else:
            run_focus_generation(db, provider, query, chunk_matches, concept_matches)


def run_focus_generation(
    db: KnowledgeDB,
    provider: Provider,
    query: str,
    chunk_matches: list[dict[str, Any]],
    concept_matches: list[tuple[Any, float]],
) -> None:
    """Generate and save fresh questions from the passages matched by a focus query."""

    context = "\n\n".join(
        f"[from: {chunk['source_title']}]\n{chunk['text']}" for chunk in chunk_matches
    )[:14000]
    topic_slug = concept_matches[0][0].topic_slug if concept_matches else "general"
    avoid = [
        prompt
        for concept, _ in concept_matches
        for prompt in db.existing_prompts_for_concept(concept.id)
    ]
    progress = st.progress(0.0, text="Contacting provider...")

    def on_progress(done: int, total: int, usage: dict[str, Any] | None) -> None:
        track_usage(provider)
        detail = usage_blurb(usage)
        message = f"Generated batch {done} of {total}"
        if detail:
            message += f" ({detail})"
        progress.progress(done / total, text=message)

    try:
        generated = generate_questions_batched(
            provider,
            text=context,
            total=QUIZ_SIZE,
            topic_slug=topic_slug,
            source_title=f"Focus: {query}",
            avoid_prompts=avoid,
            on_progress=on_progress,
        )
    except ProviderError as exc:
        track_usage(provider)
        progress.empty()
        st.error(str(exc))
        return
    result = save_generated_questions(db, generated)
    progress.progress(1.0, text="Done")
    st.success(
        f"Saved {result.saved} new questions ({result.duplicates} duplicates rejected). "
        "Start a focused round to practice them now."
    )


def start_quiz(db: KnowledgeDB, size: int = QUIZ_SIZE) -> bool:
    """Build a fresh quiz round. Returns False when nothing is available."""

    candidates = build_session(db, limit=size)
    pairs = [(candidate.concept, candidate.practice) for candidate in candidates]
    return _activate_quiz(db, pairs, size)


def start_focused_quiz(db: KnowledgeDB, concepts: list[Any], size: int = QUIZ_SIZE) -> bool:
    """Quiz round restricted to the concepts matched by a focus query."""

    today = date.today().isoformat()
    pairs = [(concept, concept.due > today) for concept in concepts]
    return _activate_quiz(db, pairs, size)


def _activate_quiz(db: KnowledgeDB, concept_pairs: list[tuple[Any, bool]], size: int) -> bool:
    items: list[dict[str, Any]] = []
    seen_questions: set[int] = set()
    for concept, practice in concept_pairs:
        question = db.get_question_for_concept(concept.id)
        if question is None or question.id in seen_questions:
            continue
        seen_questions.add(question.id)
        items.append(
            {
                "concept_id": concept.id,
                "question_id": question.id,
                "practice": practice,
                "freshened": False,
            }
        )
        if len(items) >= size:
            break
    if not items:
        return False
    st.session_state.quiz_items = items
    st.session_state.quiz_index = 0
    st.session_state.quiz_results = []
    reset_question_state()
    return True


def reset_question_state() -> None:
    st.session_state.quiz_answered = False
    st.session_state.quiz_correct = None
    st.session_state.quiz_logged = False
    st.session_state.quiz_answer_text = ""
    st.session_state.quiz_choice_index = None
    st.session_state.quiz_question_started = time.time()


def advance_quiz() -> None:
    st.session_state.quiz_index += 1
    reset_question_state()


def end_quiz() -> None:
    for key in ["quiz_items", "quiz_index", "quiz_results"]:
        st.session_state.pop(key, None)
    reset_question_state()


def render_quiz_question(
    db: KnowledgeDB,
    provider: Provider,
    provider_available: bool,
    items: list[dict[str, Any]],
    index: int,
) -> None:
    total = len(items)
    item = items[index]
    concept = db.get_concept(item["concept_id"])
    if concept is None:
        advance_quiz()
        st.rerun()
        return

    # Swap in a freshly generated variant for questions that were asked before,
    # so due concepts resurface without repeating the exact wording.
    if (
        st.session_state.get("quiz_fresh")
        and provider_available
        and not item.get("freshened")
        and not st.session_state.get("quiz_answered")
    ):
        item["freshened"] = True
        stored = db.get_question(item["question_id"])
        if stored is not None and stored.ask_count > 0:
            try:
                with st.spinner("Writing a fresh variant of this concept's question..."):
                    generated = generate_fresh_variant(db, provider, concept, count=1)
                track_usage(provider)
                saved_id = db.add_question(
                    concept_id=concept.id,
                    source_id=None,
                    chunk_id=None,
                    question_type=generated[0].question_type,
                    prompt=generated[0].prompt,
                    options=generated[0].options,
                    answer=generated[0].answer,
                    explanation=generated[0].explanation,
                    bloom=generated[0].bloom,
                )
                if saved_id is not None:
                    item["question_id"] = saved_id
            except ProviderError as exc:
                track_usage(provider)
                st.caption(f"Fresh variant unavailable ({exc}). Using a stored question.")

    question = db.get_question(item["question_id"])
    if question is None:
        advance_quiz()
        st.rerun()
        return

    st.progress(index / total, text=f"Question {index + 1} of {total}")
    score_so_far = sum(1 for result in st.session_state.quiz_results if result["correct"])
    mode = "practice" if item.get("practice") else "due review"
    st.caption(
        f"{concept.topic_slug} · {concept.title} · {mode} · {question.question_type} · {question.bloom}"
        f" · score {score_so_far}/{len(st.session_state.quiz_results)}"
    )
    st.subheader(question.prompt)

    answered: bool = st.session_state.get("quiz_answered", False)
    confidence = st.pills(
        "Confidence (set before answering)",
        options=[1, 2, 3, 4, 5],
        default=3,
        format_func=lambda level: CONFIDENCE_LABELS[level],
        key=f"quiz_conf_{index}",
    )
    confidence = confidence or 3

    if not answered:
        render_answer_input(db, provider, concept.id, question, confidence)
        return

    render_question_feedback(db, provider, provider_available, concept.id, question, confidence, index, total)


def render_answer_input(
    db: KnowledgeDB,
    provider: Provider,
    concept_id: int,
    question: Question,
    confidence: int,
) -> None:
    if question.question_type in {"single_mcq", "applied_scenario"} and question.options:
        with st.container(key="quiz-options"):
            for option_index, option in enumerate(question.options):
                label = f"{option_letter(option_index)}.  {option}"
                if st.button(label, key=f"quiz_opt_{question.id}_{option_index}", use_container_width=True):
                    correct = option_index == question.answer.get("index")
                    st.session_state.quiz_choice_index = option_index
                    finish_answer(db, provider, concept_id, question, correct, confidence, label)
                    st.rerun()
        return

    if question.question_type == "multi_select" and question.options:
        selected: list[int] = []
        for option_index, option in enumerate(question.options):
            if st.checkbox(f"{option_letter(option_index)}. {option}", key=f"quiz_ms_{question.id}_{option_index}"):
                selected.append(option_index)
        if st.button("Check answer", type="primary"):
            expected = set(question.answer.get("indices", []))
            correct = set(selected) == expected
            chosen = ", ".join(f"{option_letter(i)}. {question.options[i]}" for i in selected)
            finish_answer(db, provider, concept_id, question, correct, confidence, chosen)
            st.rerun()
        return

    response = st.text_area("Your answer", placeholder="Be precise. Vague is wrong.", key=f"quiz_txt_{question.id}")
    if st.button("Reveal expected answer", type="primary"):
        st.session_state.quiz_answered = True
        st.session_state.quiz_correct = None
        st.session_state.quiz_answer_text = response
        st.rerun()


def finish_answer(
    db: KnowledgeDB,
    provider: Provider,
    concept_id: int,
    question: Question,
    correct: bool,
    confidence: int,
    answer_text: str,
) -> None:
    st.session_state.quiz_answered = True
    st.session_state.quiz_correct = correct
    st.session_state.quiz_answer_text = answer_text
    log_quiz_review(db, provider, concept_id, question, correct, confidence)


def log_quiz_review(
    db: KnowledgeDB,
    provider: Provider,
    concept_id: int,
    question: Question,
    correct: bool,
    confidence: int,
) -> None:
    if st.session_state.get("quiz_logged"):
        return
    items = st.session_state.get("quiz_items", [])
    index = st.session_state.get("quiz_index", 0)
    practice = bool(items[index].get("practice")) if index < len(items) else False
    quality = derive_quality(correct, confidence)
    latency = time.time() - st.session_state.get("quiz_question_started", time.time())
    db.record_review(
        concept_id=concept_id,
        question_id=question.id,
        correct=correct,
        confidence=confidence,
        quality=quality,
        latency_seconds=latency,
        answer_text=st.session_state.get("quiz_answer_text", ""),
        provider=provider.name,
        update_schedule=not practice,
    )
    concept = db.get_concept(concept_id)
    st.session_state.quiz_results.append(
        {
            "concept_id": concept_id,
            "concept_title": concept.title if concept else "Unknown concept",
            "question_id": question.id,
            "prompt": question.prompt,
            "correct": correct,
            "confidence": confidence,
        }
    )
    st.session_state.quiz_logged = True


def render_question_feedback(
    db: KnowledgeDB,
    provider: Provider,
    provider_available: bool,
    concept_id: int,
    question: Question,
    confidence: int,
    index: int,
    total: int,
) -> None:
    correct = st.session_state.get("quiz_correct")
    chosen_index = st.session_state.get("quiz_choice_index")

    if question.options and question.question_type in {"single_mcq", "applied_scenario"}:
        answer_index = question.answer.get("index")
        for option_index, option in enumerate(question.options):
            letter = option_letter(option_index)
            if option_index == answer_index:
                st.markdown(f"- ✅ **{letter}. {option}**")
            elif option_index == chosen_index and correct is False:
                st.markdown(f"- ❌ ~~{letter}. {option}~~ (your pick)")
            else:
                st.markdown(f"- {letter}. {option}")

    if correct is True:
        st.success("Correct")
    elif correct is False:
        st.error("Missed")

    expected = expected_answer(question)
    if expected and question.question_type not in {"single_mcq", "applied_scenario"}:
        st.markdown(f"**Expected:** {expected}")
    if question.explanation:
        st.info(question.explanation)

    if correct is None:
        st.markdown("**Grade yourself strictly** — did your answer include the mechanism, not just the label?")
        col_hit, col_miss = st.columns(2)
        if col_hit.button("I got it", use_container_width=True):
            st.session_state.quiz_correct = True
            log_quiz_review(db, provider, concept_id, question, True, confidence)
            st.rerun()
        if col_miss.button("I missed it", use_container_width=True):
            st.session_state.quiz_correct = False
            log_quiz_review(db, provider, concept_id, question, False, confidence)
            st.rerun()
        return

    with st.expander("Feynman check (optional)"):
        feynman = st.text_area(
            "Explain the idea in your own words",
            key=f"quiz_feynman_{question.id}",
            placeholder="State the mechanism, the boundary, and the likely trap.",
        )
        if st.button("Get examiner critique") and feynman.strip():
            if not provider_available:
                st.warning("No active provider is available for critique.")
            else:
                try:
                    with st.spinner("Examining..."):
                        critique = provider.critique(question.prompt, expected, feynman)
                    track_usage(provider)
                    st.warning(critique)
                except ProviderError as exc:
                    track_usage(provider)
                    st.error(str(exc))

    label = "Next question" if index + 1 < total else "Finish round"
    if st.button(label, type="primary", use_container_width=True):
        advance_quiz()
        st.rerun()


def quiz_summary(db: KnowledgeDB) -> None:
    results: list[dict[str, Any]] = st.session_state.get("quiz_results", [])
    score = sum(1 for result in results if result["correct"])
    total = len(results)

    st.progress(1.0, text="Round complete")
    st.subheader(f"Round complete: {score}/{total}")
    if total:
        accuracy = score / total
        if accuracy >= 0.8:
            st.success("Strong round. The scheduler will push these concepts further out.")
        elif accuracy >= 0.5:
            st.warning("Mixed round. Missed concepts come back sooner — expect to see them again.")
        else:
            st.error("Rough round. These concepts are being pulled forward for drilling.")

    for result in results:
        icon = "✅" if result["correct"] else "❌"
        st.markdown(f"{icon} **{result['concept_title']}** — {result['prompt'][:120]}")

    missed = [result["concept_title"] for result in results if not result["correct"]]
    if missed:
        st.caption("Coming back soon: " + ", ".join(dict.fromkeys(missed)))

    col_more, col_done = st.columns(2)
    if col_more.button(f"{QUIZ_SIZE} more questions", type="primary", use_container_width=True):
        if start_quiz(db):
            st.rerun()
        else:
            st.info("No concepts with questions exist yet. Ingest material to build the next round.")
    if col_done.button("Done for now", use_container_width=True):
        end_quiz()
        st.rerun()


def expected_answer(question: Question) -> str:
    if "text" in question.answer:
        return str(question.answer["text"])
    if "index" in question.answer and question.options:
        index = int(question.answer["index"])
        if 0 <= index < len(question.options):
            return f"{option_letter(index)}. {question.options[index]}"
    if "indices" in question.answer and question.options:
        return "; ".join(
            f"{option_letter(index)}. {question.options[index]}" for index in question.answer["indices"]
        )
    return ""


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def ingest_page(db: KnowledgeDB, provider: Provider, provider_available: bool) -> None:
    st.header("Ingest")
    if "ingest_text" not in st.session_state:
        st.session_state.ingest_text = ""
    if "ingest_title" not in st.session_state:
        st.session_state.ingest_title = ""
    if "ingest_author" not in st.session_state:
        st.session_state.ingest_author = ""
    if "ingest_identifier" not in st.session_state:
        st.session_state.ingest_identifier = ""
    if "ingest_source_type" not in st.session_state:
        st.session_state.ingest_source_type = "book"

    uploaded = st.file_uploader(
        "Drop a PDF, Markdown, or text file",
        type=["pdf", "md", "markdown", "txt"],
        help="The file stays local. Its text appears below for review before saving or generating.",
    )
    if uploaded is not None:
        file_bytes = uploaded.getvalue()
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        if st.session_state.get("ingest_file_hash") != file_hash:
            base_name = uploaded.name.rsplit(".", 1)[0]
            if uploaded.name.lower().endswith(".pdf"):
                try:
                    with st.spinner("Extracting PDF text locally..."):
                        extracted = extract_pdf_text(file_bytes)
                    st.session_state.ingest_file_hash = file_hash
                    st.session_state.ingest_text = extracted.text
                    st.session_state.ingest_source_type = "paper"
                    if not st.session_state.ingest_title:
                        st.session_state.ingest_title = extracted.title or base_name
                    st.success(f"Extracted {extracted.page_count} pages. Review the text below before saving or generating.")
                except PDFTextExtractionError as exc:
                    st.error(str(exc))
            else:
                st.session_state.ingest_file_hash = file_hash
                st.session_state.ingest_text = file_bytes.decode("utf-8", errors="replace")
                st.session_state.ingest_source_type = "note"
                if not st.session_state.ingest_title:
                    st.session_state.ingest_title = base_name
                st.success(f"Loaded {uploaded.name}. Review the text below before saving or generating.")

    left, right = st.columns([2, 1])
    with left:
        source_type = st.selectbox("Source type", SOURCE_TYPES, key="ingest_source_type")
        title = st.text_input("Title", placeholder="Deep Learning, Ch. 6", key="ingest_title")
        author = st.text_input("Author", key="ingest_author")
        identifier = st.text_input("Identifier", key="ingest_identifier")
    with right:
        topic_slug = st.text_input("Topic", value="dl")
        bloom_hint = st.selectbox("Bloom bias", ["", *BLOOM_LEVELS])
        st.caption(f"Generation runs in rounds of {QUIZ_SIZE} questions. Ask for 10 more any time.")
    text = st.text_area(
        "Text",
        height=320,
        key="ingest_text",
        placeholder="Paste notes, chapter excerpts, paper sections, or scratch explanations.",
    )

    col1, col2 = st.columns(2)
    if col1.button("Save source"):
        if not title.strip() or not text.strip():
            st.error("Title and text are required.")
        else:
            source_id = db.add_source(source_type, title, author, identifier, tags=[topic_slug])
            chunk_ids = db.add_content(source_id, text)
            st.success(f"Saved source with {len(chunk_ids)} chunks.")

    if col2.button(f"Generate {QUIZ_SIZE} questions", type="primary"):
        if not text.strip():
            st.error("Paste text first.")
        elif not provider_available:
            st.error(f"{provider.name} is not available. Switch provider or add questions manually.")
        else:
            run_ingest_generation(
                db,
                provider,
                text=text,
                source_type=source_type,
                title=title,
                author=author,
                identifier=identifier,
                topic_slug=topic_slug,
                bloom_hint=bloom_hint,
            )

    generated = st.session_state.get("generated_questions", [])
    if generated:
        st.subheader("Review")
        keep_indices: list[int] = []
        for index, question in enumerate(generated):
            with st.expander(f"{index + 1}. {question.concept_title} · {question.question_type}"):
                st.write(question.prompt)
                for option_index, option in enumerate(question.options):
                    st.write(f"{option_letter(option_index)}. {option}")
                st.caption(question.explanation)
                if st.checkbox("Keep", value=True, key=f"keep_generated_{index}"):
                    keep_indices.append(index)
        if st.button("Save kept questions"):
            kept = [generated[index] for index in keep_indices]
            # chunk_id omitted on purpose: each concept links to the chunk of the
            # source that best matches it semantically.
            result = save_generated_questions(
                db,
                kept,
                source_id=st.session_state.get("generated_source_id"),
            )
            st.session_state.generated_questions = []
            st.success(f"Saved {result.saved}; rejected {result.duplicates} near-duplicates.")
            st.rerun()

    context = st.session_state.get("ingest_context")
    if context and not generated:
        if st.button(f"Generate {QUIZ_SIZE} more from “{context['title'] or 'this source'}”"):
            if not provider_available:
                st.error(f"{provider.name} is not available.")
            else:
                run_ingest_generation(db, provider, **context)

    st.divider()
    saved_source_generation(db, provider, provider_available, topic_slug, bloom_hint)

    st.divider()
    manual_question_form(db, default_topic=topic_slug)


def saved_source_generation(
    db: KnowledgeDB,
    provider: Provider,
    provider_available: bool,
    topic_slug: str,
    bloom_hint: str,
) -> None:
    """Generate more questions from material that was already ingested."""

    st.subheader("Generate from a saved source")
    sources = [row for row in db.list_sources() if row["chunk_count"]]
    if not sources:
        st.caption("No saved sources with text yet. Save a source above and it will show up here.")
        return
    labels = {
        int(row["id"]): f"{row['title']} · {row['type']} · {row['chunk_count']} chunks"
        for row in sources
    }
    chosen_id = st.selectbox(
        "Saved source",
        options=list(labels),
        format_func=lambda source_id: labels[source_id],
        key="saved_source_choice",
    )
    if st.button(f"Generate {QUIZ_SIZE} questions from this source", key="saved_source_generate"):
        if not provider_available:
            st.error(f"{provider.name} is not available.")
            return
        source = next(row for row in sources if int(row["id"]) == chosen_id)
        text = db.source_text(chosen_id)
        if not text.strip():
            st.error("This source has no stored text to generate from.")
            return
        run_ingest_generation(
            db,
            provider,
            text=text,
            source_type=source["type"],
            title=source["title"],
            author=source["author"] or "",
            identifier=source["identifier"] or "",
            topic_slug=topic_slug,
            bloom_hint=bloom_hint,
            source_id=chosen_id,
        )


def run_ingest_generation(
    db: KnowledgeDB,
    provider: Provider,
    text: str,
    source_type: str,
    title: str,
    author: str,
    identifier: str,
    topic_slug: str,
    bloom_hint: str,
    source_id: int | None = None,
) -> None:
    """Generate a 10-question round in small batches with visible progress and usage.

    Pass ``source_id`` to regenerate from an already-saved source without re-adding it.
    """

    if source_id is None:
        source_id = db.add_source(source_type, title or "Untitled source", author, identifier, tags=[topic_slug])
        db.add_content(source_id, text)
    previous_context = st.session_state.get("ingest_context") or {}
    if previous_context.get("text") != text:
        st.session_state.ingest_seen_prompts = []
    # Steer away from questions already saved for this source plus unsaved
    # candidates generated earlier this session.
    seen_prompts: list[str] = st.session_state.get("ingest_seen_prompts", [])
    avoid_prompts = db.prompts_for_source(source_id) + seen_prompts

    progress = st.progress(0.0, text="Contacting provider...")

    def on_progress(done_batches: int, total_batches: int, usage: dict[str, Any] | None) -> None:
        track_usage(provider)
        detail = usage_blurb(usage)
        message = f"Generated batch {done_batches} of {total_batches}"
        if detail:
            message += f" ({detail})"
        progress.progress(done_batches / total_batches, text=message)

    try:
        generated = generate_questions_batched(
            provider,
            text=text,
            total=QUIZ_SIZE,
            topic_slug=topic_slug,
            source_title=title,
            bloom_hint=bloom_hint,
            avoid_prompts=avoid_prompts,
            on_progress=on_progress,
        )
    except ProviderError as exc:
        track_usage(provider)
        progress.empty()
        st.error(str(exc))
        return

    st.session_state.generated_questions = generated
    st.session_state.generated_source_id = source_id
    st.session_state.ingest_seen_prompts = seen_prompts + [question.prompt for question in generated]
    st.session_state.ingest_context = {
        "text": text,
        "source_type": source_type,
        "title": title,
        "author": author,
        "identifier": identifier,
        "topic_slug": topic_slug,
        "bloom_hint": bloom_hint,
        "source_id": source_id,
    }
    progress.progress(1.0, text=f"Generated {len(generated)} candidates.")
    st.success(f"Generated {len(generated)} candidates. Review and save the keepers below.")
    st.rerun()


def manual_question_form(db: KnowledgeDB, default_topic: str = "general", concept_id: int | None = None) -> None:
    with st.expander("Manual question", expanded=concept_id is not None):
        topic = st.text_input("Topic slug", value=default_topic, key=f"manual_topic_{concept_id or 'new'}")
        if concept_id is None:
            concept_title = st.text_input("Concept", key="manual_concept")
            concept_summary = st.text_area("Concept summary", key="manual_summary")
        else:
            concept = db.get_concept(concept_id)
            concept_title = concept.title if concept else "Untitled concept"
            concept_summary = concept.summary if concept else ""
            st.caption(concept_title)
        question_type = st.selectbox("Question type", QUESTION_TYPES, key=f"manual_qt_{concept_id or 'new'}")
        prompt = st.text_area("Prompt", key=f"manual_prompt_{concept_id or 'new'}")
        bloom = st.selectbox("Bloom", BLOOM_LEVELS, index=1, key=f"manual_bloom_{concept_id or 'new'}")
        options: list[str] = []
        answer: dict[str, Any]
        if question_type in {"single_mcq", "applied_scenario"}:
            options = [st.text_input(f"Option {option_letter(i)}", key=f"manual_opt_{concept_id}_{i}") for i in range(4)]
            answer = {"index": st.selectbox("Correct option", [0, 1, 2, 3], format_func=option_letter)}
        elif question_type == "multi_select":
            options = [st.text_input(f"Option {option_letter(i)}", key=f"manual_ms_{concept_id}_{i}") for i in range(5)]
            selected = st.multiselect("Correct options", [0, 1, 2, 3, 4], format_func=option_letter)
            answer = {"indices": selected}
        else:
            answer = {"text": st.text_area("Expected answer", key=f"manual_answer_{concept_id or 'new'}")}
        explanation = st.text_area("Explanation", key=f"manual_explanation_{concept_id or 'new'}")
        if st.button("Add", key=f"manual_add_{concept_id or 'new'}"):
            if not prompt.strip() or not concept_title.strip():
                st.error("Concept and prompt are required.")
                return
            with st.spinner("Saving..."):
                actual_concept_id = concept_id or db.find_or_create_concept(concept_title, concept_summary, topic)
                saved = db.add_question(
                    concept_id=actual_concept_id,
                    source_id=None,
                    chunk_id=None,
                    question_type=question_type,
                    prompt=prompt,
                    options=[option for option in options if option],
                    answer=answer,
                    explanation=explanation,
                    bloom=bloom,
                )
            if saved is None:
                st.warning("That question looks like a duplicate.")
            else:
                st.success("Saved.")


def library_page(db: KnowledgeDB) -> None:
    st.header("Library")
    query = st.text_input("Search")
    if query:
        for row in db.search(query):
            with st.container(border=True):
                st.caption(f"{row['kind']} #{row['ref_id']}")
                st.write(row["title"])
                st.caption(str(row["snippet"])[:500])

    concepts_tab, sources_tab = st.tabs(["Concepts", "Sources"])
    with concepts_tab:
        rows = db.list_concepts()
        st.dataframe(
            [
                {
                    "topic": row["topic_slug"],
                    "concept": row["title"],
                    "mastery": row["mastery"],
                    "due": row["due"],
                    "leech": bool(row["leech"]),
                    "questions": row["question_count"],
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
    with sources_tab:
        rows = db.list_sources()
        st.dataframe(
            [
                {
                    "type": row["type"],
                    "title": row["title"],
                    "author": row["author"],
                    "chunks": row["chunk_count"],
                    "added": row["created_at"],
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )


def dashboard_page(db: KnowledgeDB) -> None:
    st.header("Dashboard")
    stats = db.stats()
    cols = st.columns(5)
    cols[0].metric("Sources", stats["sources"])
    cols[1].metric("Concepts", stats["concepts"])
    cols[2].metric("Questions", stats["questions"])
    cols[3].metric("Reviews", stats["reviews"])
    cols[4].metric("Due", stats["due"])

    mastery = db.topic_mastery()
    if mastery:
        st.subheader("Mastery")
        st.bar_chart(mastery)
    calibration = db.calibration()
    if calibration:
        st.subheader("Calibration")
        st.bar_chart(calibration)

    weak = db.weak_spots()
    if weak:
        st.subheader("Weak Spots")
        st.dataframe(
            [
                {
                    "topic": row["topic_slug"],
                    "concept": row["title"],
                    "mastery": row["mastery"],
                    "accuracy": row["accuracy"],
                    "overconfident misses": row["overconfident_misses"],
                    "leech": bool(row["leech"]),
                }
                for row in weak
            ],
            use_container_width=True,
            hide_index=True,
        )


def coaching_page(db: KnowledgeDB, provider: Provider, provider_available: bool) -> None:
    st.header("Coaching")
    if st.button("Generate report", type="primary"):
        if not provider_available:
            st.error(f"{provider.name} is not available.")
        else:
            try:
                with st.spinner("Building diagnostic report..."):
                    report = provider.analyze_weakspots(db.coaching_context())
                track_usage(provider)
                db.save_coaching_report(provider.name, report)
                st.success("Saved report.")
            except ProviderError as exc:
                track_usage(provider)
                st.error(str(exc))
    for report in db.recent_coaching_reports():
        with st.expander(f"{report['ts']} · {report['provider']}", expanded=False):
            st.write(report["report"])


def settings_page(config: AppConfig, provider_available: bool) -> None:
    st.header("Settings")
    st.session_state.provider = st.selectbox(
        "Provider",
        ["claude_code", "anthropic", "openai", "ollama", "manual"],
        index=["claude_code", "anthropic", "openai", "ollama", "manual"].index(
            st.session_state.get("provider", config.provider)
        ),
    )
    st.session_state.model = st.text_input("Model", value=st.session_state.get("model", config.model))
    st.session_state.claude_command = st.text_input(
        "Claude Code command",
        value=st.session_state.get("claude_command", config.claude_command),
        help='Default uses `claude -p`. Include "{prompt}" if your command needs a custom prompt position.',
    )
    st.session_state.provider_timeout = st.number_input(
        "Provider timeout (seconds)",
        min_value=30,
        max_value=1200,
        step=30,
        value=int(st.session_state.get("provider_timeout", config.provider_timeout_seconds)),
        help="How long one LLM call may run. Generation is batched into small calls, so the default is plenty.",
    )
    st.session_state.anthropic_key = st.text_input(
        "Anthropic API key",
        value=st.session_state.get("anthropic_key", ""),
        type="password",
    )
    st.session_state.openai_key = st.text_input(
        "OpenAI API key",
        value=st.session_state.get("openai_key", ""),
        type="password",
    )
    st.session_state.ollama_url = st.text_input("Ollama URL", value=st.session_state.get("ollama_url", config.ollama_url))
    st.session_state.ollama_model = st.text_input(
        "Ollama model",
        value=st.session_state.get("ollama_model", config.ollama_model),
    )
    if provider_available:
        st.success("Provider is ready.")
    else:
        st.warning("Provider is not ready; manual study and entry still work.")
    st.caption(f"Database: {config.db_path}")


def apply_theme() -> None:
    """Light-touch polish on top of the native theme in .streamlit/config.toml.

    Colors and widget styling come from Streamlit's theming (which keeps every
    widget readable); this CSS only adds spacing, card treatment, and hover
    feedback. Never override backgrounds or text colors here.
    """

    st.markdown(
        """
        <style>
        h1, h2, h3 {
            letter-spacing: -0.01em;
        }
        /* Roomier, clearer sidebar navigation */
        section[data-testid="stSidebar"] [role="radiogroup"] label {
            padding: 0.3rem 0.4rem;
            border-radius: 0.5rem;
            width: 100%;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: rgba(52, 211, 153, 0.10);
        }
        section[data-testid="stSidebar"] [role="radiogroup"] p {
            font-size: 1.02rem;
        }
        /* Metric cards */
        div[data-testid="stMetric"] {
            background: #1a2026;
            border: 1px solid #2c343d;
            border-radius: 0.6rem;
            padding: 0.7rem 0.9rem;
        }
        /* Answer choices read like a list: left-aligned, roomy */
        .st-key-quiz-options .stButton > button {
            justify-content: flex-start;
            text-align: left;
            padding: 0.65rem 1rem;
        }
        .st-key-quiz-options .stButton > button p {
            text-align: left;
        }
        /* Satisfying press feedback on answer buttons */
        .stButton > button {
            transition: transform 0.05s ease-in-out, border-color 0.1s ease-in-out;
        }
        .stButton > button:hover {
            border-color: #34d399;
        }
        .stButton > button:active {
            transform: scale(0.99);
        }
        /* Primary actions get real weight */
        .stButton > button[kind="primary"] {
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
