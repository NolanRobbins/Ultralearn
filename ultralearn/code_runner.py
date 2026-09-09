"""Run a learner's Python against hidden checks, locally.

The editor is the point: implement a function, hit Run, see which checks
passed. Execution is a subprocess of this machine's interpreter so PyTorch
and the rest of the study venv are available. There is no remote judge,
leaderboard, or contest chrome.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

_HARNESS = r"""
import json
import traceback

results = []
try:
    import checks
    cases = getattr(checks, "CHECKS", None)
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("This problem has no checks to run.")
    for item in cases:
        name, fn = item[0], item[1]
        try:
            fn()
            results.append({"name": name, "ok": True, "error": ""})
        except Exception as exc:
            results.append({
                "name": name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:800],
            })
except Exception as exc:
    results.append({
        "name": "load",
        "ok": False,
        "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"[:1200],
    })

print("ULTRALEARN_RESULTS:" + json.dumps(results))
"""


@dataclass
class CheckResult:
    name: str
    ok: bool
    error: str = ""


@dataclass
class RunResult:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    runtime_ms: int = 0
    timed_out: bool = False
    error: str = ""

    @property
    def passed_count(self) -> int:
        return sum(1 for item in self.checks if item.ok)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.checks if not item.ok)


def run_solution(
    code: str,
    tests: str,
    timeout_seconds: float = 8.0,
    python_executable: str | None = None,
) -> RunResult:
    """Write ``solution.py`` + hidden ``checks.py`` and execute them."""

    code = code or ""
    tests = tests or ""
    if not code.strip():
        return RunResult(passed=False, error="The editor is empty.")
    if not tests.strip():
        return RunResult(passed=False, error="This problem has no hidden checks.")

    executable = python_executable or sys.executable
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ultralearn-code-") as raw:
        root = Path(raw)
        (root / "solution.py").write_text(code, encoding="utf-8")
        (root / "checks.py").write_text(tests, encoding="utf-8")
        (root / "_harness.py").write_text(_HARNESS, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                [executable, "-B", str(root / "_harness.py")],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return RunResult(
                passed=False,
                stdout=stdout[-4000:],
                stderr=stderr[-4000:],
                runtime_ms=int((time.monotonic() - started) * 1000),
                timed_out=True,
                error=f"Timed out after {timeout_seconds:.0f}s.",
            )

    runtime_ms = int((time.monotonic() - started) * 1000)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    checks = _parse_results(stdout)
    if not checks:
        error = stderr.strip() or stdout.strip() or f"Process exited {completed.returncode}."
        return RunResult(
            passed=False,
            stdout=stdout[-4000:],
            stderr=stderr[-4000:],
            runtime_ms=runtime_ms,
            error=error[:800],
        )
    return RunResult(
        passed=all(item.ok for item in checks) and bool(checks),
        checks=checks,
        stdout=_public_stdout(stdout)[-4000:],
        stderr=stderr[-4000:],
        runtime_ms=runtime_ms,
    )


def _parse_results(stdout: str) -> list[CheckResult]:
    marker = "ULTRALEARN_RESULTS:"
    for line in reversed(stdout.splitlines()):
        if line.startswith(marker):
            payload = json.loads(line[len(marker) :])
            return [
                CheckResult(
                    name=str(item.get("name") or "check"),
                    ok=bool(item.get("ok")),
                    error=str(item.get("error") or ""),
                )
                for item in payload
            ]
    return []


def _public_stdout(stdout: str) -> str:
    return "\n".join(
        line for line in stdout.splitlines() if not line.startswith("ULTRALEARN_RESULTS:")
    )
