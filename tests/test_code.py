from ultralearn.code_runner import run_solution
from ultralearn.db import KnowledgeDB


STARTER = """def add(a, b):
    raise NotImplementedError
"""

TESTS = """
from solution import add

CHECKS = [
    ("one plus one", lambda: None if add(1, 1) == 2 else (_ for _ in ()).throw(AssertionError(add(1, 1)))),
    ("negatives", lambda: None if add(-2, 5) == 3 else (_ for _ in ()).throw(AssertionError(add(-2, 5)))),
]
"""


def test_run_solution_reports_each_check():
    result = run_solution("def add(a, b):\n    return a + b\n", TESTS, timeout_seconds=4)
    assert result.passed
    assert result.passed_count == 2
    assert result.failed_count == 0


def test_run_solution_catches_a_wrong_implementation():
    result = run_solution("def add(a, b):\n    return a - b\n", TESTS, timeout_seconds=4)
    assert result.passed is False
    assert result.failed_count == 2


def test_run_solution_times_out():
    result = run_solution(
        "def add(a, b):\n    while True:\n        pass\n",
        TESTS,
        timeout_seconds=0.4,
    )
    assert result.timed_out
    assert result.passed is False


def test_empty_editor_does_not_spawn():
    result = run_solution("  \n", TESTS)
    assert result.passed is False
    assert "empty" in result.error.lower()


def test_code_problems_seed_and_hide_tests(tmp_path):
    db = KnowledgeDB(tmp_path / "code.db")
    db.initialize()
    problems = db.list_code_problems()
    assert len(problems) >= 10
    public = db.get_code_problem(int(problems[0]["id"]))
    assert public is not None
    assert "tests" not in public.keys()
    hidden = db.get_code_problem(int(problems[0]["id"]), include_tests=True)
    assert hidden is not None
    assert "CHECKS" in hidden["tests"]


def test_code_problem_links_to_a_matching_concept(tmp_path):
    db = KnowledgeDB(tmp_path / "code.db")
    db.initialize()
    db.find_or_create_concept(
        "GRPO avoids separate value models",
        "Group relative advantages, no critic.",
        "dl",
    )
    db.initialize()
    linked = [
        row
        for row in db.list_code_problems()
        if row["concept_title"] and "GRPO" in row["concept_title"]
    ]
    assert linked
    assert any(row["slug"] == "group-advantages" for row in linked)
