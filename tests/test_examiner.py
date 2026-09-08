"""Tests for the examiner.

The point of these is that vagueness must not earn credit, and that a broken
grader must never be mistaken for a pass.
"""

import json

import pytest

from ultralearn.examiner import GRADE_SCHEMA, GradeResult, grade_answer, parse_grade
from ultralearn.providers import ManualProvider, PromptProvider, ProviderError


class FakeExaminer(PromptProvider):
    name = "fake"

    def __init__(self, response: str) -> None:
        self.response = response
        self.schema = None

    def available(self) -> bool:
        return True

    def _complete(self, prompt: str, schema=None) -> str:
        self.schema = schema
        self.prompt = prompt
        return self.response


def test_structured_verdict_is_parsed():
    payload = json.dumps(
        {
            "verdict": "partial",
            "score": 2,
            "missing": ["the causal link from saturation to vanishing gradients"],
            "misconception": "treats depth itself as the cause",
            "probe": "What changes if you swap in ReLU?",
            "fix": "State the mechanism, not the symptom.",
        }
    )
    result = parse_grade(payload)

    assert result.verdict == "partial"
    assert result.correct is False
    assert result.score == 2
    assert result.missing == ["the causal link from saturation to vanishing gradients"]
    assert result.misconception == "treats depth itself as the cause"


def test_grading_requests_the_schema():
    provider = FakeExaminer(json.dumps({"verdict": "correct", "score": 5, "missing": [],
                                        "misconception": "", "probe": "p", "fix": "f"}))
    result = grade_answer(provider, "Why?", "Because X causes Y.", "X causes Y via Z.")

    assert provider.schema is GRADE_SCHEMA
    assert result.correct is True


def test_fenced_and_chatty_responses_still_parse():
    raw = (
        "Sure, here's my assessment:\n```json\n"
        '{"verdict":"incorrect","score":1,"missing":["everything"],'
        '"misconception":"confuses variance with bias","probe":"q","fix":"f"}\n'
        "```\nHope that helps!"
    )
    result = parse_grade(raw)
    assert result.verdict == "incorrect"
    assert result.misconception == "confuses variance with bias"


def test_a_high_score_cannot_smuggle_in_a_low_one():
    """"correct" with a failing score is a hedge; the verdict is downgraded."""

    result = parse_grade(
        json.dumps({"verdict": "correct", "score": 1, "missing": [], "misconception": "",
                    "probe": "", "fix": ""})
    )
    assert result.verdict == "partial"


def test_blank_answers_are_marked_incorrect_without_calling_the_provider():
    provider = FakeExaminer("should not be used")
    result = grade_answer(provider, "Why?", "Because X.", "   ")

    assert result.verdict == "incorrect"
    assert result.score == 0
    assert provider.schema is None


def test_unreadable_grader_output_does_not_count_as_a_pass():
    result = parse_grade("the model rambled and never returned JSON")
    assert result.correct is False
    assert result.score == 0
    assert result.graded_by == "self"


def test_missing_provider_falls_back_to_self_grading():
    result = grade_answer(ManualProvider(), "Why?", "Because X.", "Because X.")
    assert result.graded_by == "self"
    assert result.score == 0


def test_provider_errors_propagate_for_the_caller_to_report():
    class Broken(FakeExaminer):
        def _complete(self, prompt: str, schema=None) -> str:
            raise ProviderError("Claude Code is not logged in.")

    with pytest.raises(ProviderError):
        grade_answer(Broken(""), "Why?", "Because X.", "Because X.")


def test_scores_are_clamped_to_the_rubric():
    result = parse_grade(
        json.dumps({"verdict": "correct", "score": 99, "missing": [], "misconception": "",
                    "probe": "", "fix": ""})
    )
    assert result.score == 5


def test_unavailable_result_is_explicit_about_why():
    result = GradeResult.unavailable("Provider timed out.")
    assert result.graded_by == "self"
    assert "timed out" in result.fix
