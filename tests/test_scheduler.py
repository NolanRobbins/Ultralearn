from datetime import date

from ultralearn.scheduler import derive_quality, schedule_review_state


def test_confident_wrong_is_harshest_grade():
    assert derive_quality(False, 5) == 0
    assert derive_quality(False, 4) == 0
    assert derive_quality(False, 2) == 2


def test_correct_quality_scales_with_confidence():
    assert derive_quality(True, 1) == 3
    assert derive_quality(True, 5) == 5


def test_concept_level_sm2_progression():
    today = date(2026, 7, 2)
    first = schedule_review_state(2.5, 0, 0, 5, today)
    assert first.repetitions == 1
    assert first.interval == 1
    assert first.due == "2026-07-03"

    second = schedule_review_state(first.ease, first.interval, first.repetitions, 5, today)
    assert second.repetitions == 2
    assert second.interval == 6
    assert second.due == "2026-07-08"


def test_failed_review_resets_repetitions_but_not_below_minimum_ease():
    state = schedule_review_state(1.31, 12, 4, 0, date(2026, 7, 2))
    assert state.repetitions == 0
    assert state.interval == 1
    assert state.ease == 1.3
