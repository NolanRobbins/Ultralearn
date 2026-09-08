import json

import pytest

from ultralearn.generation import generate_questions_batched
from ultralearn.models import ProviderQuestion
from ultralearn.providers import ClaudeCodeProvider, Provider, ProviderError


def make_question(prompt: str) -> ProviderQuestion:
    return ProviderQuestion(
        concept_title="Backprop chain rule",
        concept_summary="Gradients compose through nested functions.",
        topic_slug="dl",
        question_type="short_answer",
        prompt=prompt,
        options=[],
        answer={"text": "expected"},
        explanation="",
        bloom="apply",
    )


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, batches: list[list[ProviderQuestion]]) -> None:
        self.batches = batches
        self.calls: list[dict] = []

    def available(self) -> bool:
        return True

    def generate_questions(
        self,
        text,
        n,
        topic_slug,
        source_title="",
        concept_title="",
        bloom_hint="",
        avoid_prompts=None,
    ):
        self.calls.append({"n": n, "avoid": list(avoid_prompts or [])})
        self.last_usage = {"provider": self.name, "duration_ms": 1000, "cost_usd": 0.01}
        return self.batches[len(self.calls) - 1]

    def critique(self, question, expected_answer, learner_answer):
        return ""

    def analyze_weakspots(self, report_context):
        return ""


def test_batched_generation_splits_calls_and_passes_avoid_list():
    provider = FakeProvider(
        [
            [make_question("How does gradient flow break in scenario A?")],
            [make_question("Diagnose the vanishing gradient in setup B.")],
        ]
    )
    progress: list[tuple[int, int]] = []
    questions = generate_questions_batched(
        provider,
        text="notes",
        total=2,
        batch_size=1,
        on_progress=lambda done, total, usage: progress.append((done, total)),
    )
    assert len(questions) == 2
    assert [call["n"] for call in provider.calls] == [1, 1]
    # The second batch is told about the first batch's prompt.
    assert provider.calls[1]["avoid"] == ["How does gradient flow break in scenario A?"]
    assert progress == [(1, 2), (2, 2)]


def test_batched_generation_drops_cross_batch_duplicates():
    same = make_question("How does gradient flow break in scenario A?")
    provider = FakeProvider([[same], [same]])
    questions = generate_questions_batched(provider, text="notes", total=2, batch_size=1)
    assert len(questions) == 1


def test_batched_generation_raises_when_everything_is_duplicate():
    same = make_question("How does gradient flow break in scenario A?")
    provider = FakeProvider([[same]])
    with pytest.raises(ProviderError):
        generate_questions_batched(
            provider,
            text="notes",
            total=1,
            batch_size=1,
            avoid_prompts=[same.prompt],
        )


def test_claude_code_json_envelope_unwraps_result_and_records_usage():
    provider = ClaudeCodeProvider()
    envelope = json.dumps(
        {
            "type": "result",
            "result": "[]",
            "total_cost_usd": 0.0123,
            "duration_ms": 4200,
            "usage": {"input_tokens": 900, "output_tokens": 350},
        }
    )
    assert provider._extract_result(envelope) == "[]"
    assert provider.last_usage == {
        "provider": "claude_code",
        "cost_usd": 0.0123,
        "duration_ms": 4200,
        "input_tokens": 900,
        "output_tokens": 350,
    }


def test_claude_code_plain_text_passes_through():
    provider = ClaudeCodeProvider()
    assert provider._extract_result('[{"prompt": "not an envelope"}]') == '[{"prompt": "not an envelope"}]'
    assert provider.last_usage is None


def test_claude_code_error_envelope_raises():
    provider = ClaudeCodeProvider()
    envelope = json.dumps({"type": "result", "is_error": True, "result": "usage limit reached"})
    with pytest.raises(ProviderError):
        provider._extract_result(envelope)
