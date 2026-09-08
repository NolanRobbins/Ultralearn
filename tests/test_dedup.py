from ultralearn.dedup import QuestionDeduper, fingerprint, normalize_text, similarity


def test_normalization_collapses_punctuation_and_case():
    assert normalize_text("Backprop: Chain Rule!") == "backprop chain rule"


def test_fingerprint_matches_normalized_duplicates():
    assert fingerprint("What is pot odds?") == fingerprint("what is pot odds")


def test_near_duplicate_is_rejected():
    deduper = QuestionDeduper(["Why does backpropagation need the chain rule?"])
    assert deduper.is_duplicate("Why does backprop need the chain rule")


def test_different_prompt_is_allowed():
    deduper = QuestionDeduper(["Why does backpropagation need the chain rule?"])
    assert not deduper.is_duplicate("When would put-call parity be violated?")
    assert similarity("abc", "xyz") < 0.5
