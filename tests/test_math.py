from ultralearn.db import KnowledgeDB
from ultralearn.math_grader import answers_match, grade_phrases, why_phrases


def test_grade_phrases_hits_the_mechanism():
    grade = grade_phrases(
        "Softmax turns logits into a probability by exponentiating each one and dividing by the sum",
        ["probability", "exponent", "sum", "logit"],
    )
    assert grade.passed
    assert grade.verdict == "correct"


def test_grade_phrases_rejects_a_label_only_answer():
    grade = grade_phrases("it is the softmax formula", ["probability", "exponent", "sum", "logit"])
    assert grade.passed is False
    assert "probability" in grade.missing


def test_answers_match_aliases():
    assert answers_match("exp(z_i)", "e^{z_i}", ["exp(z_i)", "exponential of the logit"])
    assert answers_match("the group mean", "the mean reward of the group", ["group mean"])
    assert answers_match("", "e^{z_i}") is False


def test_why_phrases_are_gradable():
    phrases = why_phrases("Stops a collapse when every rollout in the group got the same reward.")
    assert phrases
    grade = grade_phrases("without it the std is zero and the group collapses", phrases, threshold=0.5)
    assert grade.score > 0


def test_math_formulas_seed_and_hide_spoken(tmp_path):
    db = KnowledgeDB(tmp_path / "math.db")
    db.initialize()
    formulas = db.list_math_formulas()
    assert len(formulas) >= 10
    public = db.get_math_formula(int(formulas[0]["id"]))
    assert public is not None
    assert "spoken" not in public.keys()
    hidden = db.get_math_formula(int(formulas[0]["id"]), include_answers=True)
    assert hidden is not None
    assert hidden["spoken"]


def test_math_formula_links_to_a_matching_concept(tmp_path):
    db = KnowledgeDB(tmp_path / "math.db")
    db.initialize()
    db.find_or_create_concept(
        "GRPO avoids separate value models",
        "Group relative advantages, no critic.",
        "dl",
    )
    db.initialize()
    linked = [
        row
        for row in db.list_math_formulas()
        if row["concept_title"] and "GRPO" in row["concept_title"]
    ]
    assert linked
    assert any(row["slug"] == "grpo-advantage" for row in linked)
