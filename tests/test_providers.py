import pytest

from ultralearn.providers import ProviderError, parse_questions


def test_parse_questions_supports_legacy_answer_index():
    parsed = parse_questions(
        """
        ```json
        [
          {
            "concept_title": "Backprop chain rule",
            "concept_summary": "Gradients compose through nested functions.",
            "topic_slug": "dl",
            "question_type": "single_mcq",
            "prompt": "Why does backprop use the chain rule?",
            "options": ["A", "B", "C", "D"],
            "answer_index": 1,
            "explanation": "Because each layer is a nested function.",
            "bloom": "apply"
          }
        ]
        ```
        """
    )
    assert len(parsed) == 1
    assert parsed[0].answer == {"index": 1}
    assert parsed[0].concept_title == "Backprop chain rule"


def test_parse_questions_rejects_invalid_json():
    with pytest.raises(ProviderError):
        parse_questions("not json")


def _mcq(prompt: str, extra: str = "") -> str:
    return (
        "{"
        '"concept_title": "C", "concept_summary": "s", "topic_slug": "dl", '
        '"question_type": "single_mcq", '
        f'"prompt": "{prompt}", '
        '"options": ["A", "B", "C", "D"], "answer": {"index": 0}, '
        f'"explanation": "why {extra}", "bloom": "apply"'
        "}"
    )


def test_parse_questions_recovers_good_items_when_one_is_malformed():
    # Second object has an unescaped quote inside "explanation", invalidating the array.
    raw = (
        "[\n"
        + _mcq("First question") + ",\n"
        + '{"concept_title": "C", "concept_summary": "s", "topic_slug": "dl", '
        + '"question_type": "single_mcq", "prompt": "Broken", '
        + '"options": ["A", "B", "C", "D"], "answer": {"index": 0}, '
        + '"explanation": "He said "hi" to the net", "bloom": "apply"},\n'
        + _mcq("Third question") + "\n"
        "]"
    )
    parsed = parse_questions(raw)
    prompts = {question.prompt for question in parsed}
    assert "First question" in prompts
    assert "Third question" in prompts
    assert len(parsed) == 2  # the malformed middle item is skipped


def test_parse_questions_tolerates_trailing_commas_and_fences():
    raw = "```json\n[\n" + _mcq("Only question") + ",\n]\n```"
    parsed = parse_questions(raw)
    assert len(parsed) == 1
    assert parsed[0].prompt == "Only question"
