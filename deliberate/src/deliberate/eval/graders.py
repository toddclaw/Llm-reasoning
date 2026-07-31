"""Deterministic graders.

Phase 1 grades with checks, not opinions — the same "provenance over claims"
discipline as Nightshift, applied to eval. A judge-model grader is a later addition;
everything here is deterministic and offline-testable.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runner import Completion
from .task import GradeSpec, Task

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_CODE_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]*)\s*\n(.*?)```", re.DOTALL)


@dataclass
class GradeResult:
    passed: bool
    score: float  # 0.0..1.0
    detail: str
    # Tri-state: True/False when the task involves tools, None when it doesn't.
    tool_call_valid: bool | None = None


def grade(task: Task, completion: Completion) -> GradeResult:
    if completion.error is not None:
        return GradeResult(False, 0.0, f"runner error: {completion.error}",
                           tool_call_valid=False if task.has_tools else None)
    spec = task.grade
    fn = _GRADERS.get(spec.type)
    if fn is None:  # pragma: no cover - guarded by the pydantic Literal
        return GradeResult(False, 0.0, f"unknown grader type {spec.type!r}")
    return fn(spec, completion)


# -- helpers --------------------------------------------------------------

def _norm(text: str, spec: GradeSpec) -> str:
    if spec.strip:
        text = text.strip()
    if spec.ignore_case:
        text = text.lower()
    return text


def _tool_calls_valid(completion: Completion) -> bool:
    """Every tool call has a name and JSON-parseable arguments."""
    calls = completion.tool_calls
    if not calls:
        return False
    for call in calls:
        fn = call.get("function") or {}
        if not fn.get("name"):
            return False
        args = fn.get("arguments")
        if not isinstance(args, str):
            return False
        try:
            json.loads(args)
        except (json.JSONDecodeError, ValueError):
            return False
    return True


def _subset(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return all(k in actual and actual[k] == v for k, v in expected.items())


# -- graders --------------------------------------------------------------

def _grade_exact(spec: GradeSpec, c: Completion) -> GradeResult:
    got = _norm(c.text, spec)
    want = _norm(str(spec.expected), spec)
    ok = got == want
    return GradeResult(ok, float(ok), f"exact: got {got!r} want {want!r}")


def _grade_contains(spec: GradeSpec, c: Completion) -> GradeResult:
    got = _norm(c.text, spec)
    want = _norm(str(spec.expected), spec)
    ok = want in got
    return GradeResult(ok, float(ok), f"contains {want!r}: {ok}")


def _grade_regex(spec: GradeSpec, c: Completion) -> GradeResult:
    flags = re.IGNORECASE if spec.ignore_case else 0
    ok = re.search(str(spec.expected), c.text, flags) is not None
    return GradeResult(ok, float(ok), f"regex {spec.expected!r}: {ok}")


def _grade_numeric(spec: GradeSpec, c: Completion) -> GradeResult:
    m = _NUMBER_RE.search(c.text)
    if m is None:
        return GradeResult(False, 0.0, f"no number found in {c.text!r}")
    got = float(m.group())
    want = float(spec.expected)
    ok = abs(got - want) <= spec.tolerance
    return GradeResult(ok, float(ok), f"numeric: got {got} want {want} tol {spec.tolerance}")


def _grade_tool_call(spec: GradeSpec, c: Completion) -> GradeResult:
    valid = _tool_calls_valid(c)
    if not valid:
        return GradeResult(False, 0.0, "no valid tool_calls (missing/prose/bad args)",
                           tool_call_valid=False)
    first = c.tool_calls[0]["function"]
    name = first.get("name")
    if spec.expected_name and name != spec.expected_name:
        return GradeResult(False, 0.0, f"tool name {name!r} != {spec.expected_name!r}",
                           tool_call_valid=True)
    if spec.expected_args:
        try:
            args = json.loads(first.get("arguments") or "{}")
        except (json.JSONDecodeError, ValueError):
            return GradeResult(False, 0.0, "tool arguments not JSON", tool_call_valid=False)
        if not _subset(spec.expected_args, args):
            return GradeResult(False, 0.0, f"args {args} missing {spec.expected_args}",
                               tool_call_valid=True)
    return GradeResult(True, 1.0, f"tool_call {name} ok", tool_call_valid=True)


def _grade_json_schema(spec: GradeSpec, c: Completion) -> GradeResult:
    try:
        obj = json.loads(c.text)
    except (json.JSONDecodeError, ValueError):
        return GradeResult(False, 0.0, "content is not valid JSON")
    if spec.schema_def is None:
        return GradeResult(True, 1.0, "valid JSON (no schema given)")
    import jsonschema  # local import: only needed for this grader

    try:
        jsonschema.validate(obj, spec.schema_def)
    except jsonschema.ValidationError as exc:
        return GradeResult(False, 0.0, f"schema violation: {exc.message}")
    return GradeResult(True, 1.0, "json matches schema")


def _grade_any(spec: GradeSpec, c: Completion) -> GradeResult:
    """Transparency check: passed if there is a non-empty answer (content or a call)."""
    ok = bool(c.text.strip()) or bool(c.tool_calls)
    return GradeResult(ok, float(ok), "non-empty response" if ok else "empty response")


def extract_code(text: str) -> str:
    """Pull code out of a model answer: the first fenced block, else the whole text."""
    m = _CODE_FENCE_RE.search(text)
    return m.group(1) if m else text


def _grade_exec(spec: GradeSpec, c: Completion) -> GradeResult:
    """Run the model's code against tests in an isolated subprocess. Python only.

    SECURITY: this executes model-generated code. It runs `python -I` (isolated) in a
    temp dir with a wall-clock timeout — adequate for a controlled eval on your own
    machine, NOT a hardened sandbox. Only run suites you trust.
    """
    if spec.language != "python":
        return GradeResult(False, 0.0, f"exec grader supports python only, got {spec.language!r}")
    program = "\n\n".join(p for p in (spec.setup, extract_code(c.text), spec.tests) if p)
    with tempfile.TemporaryDirectory() as d:
        prog = Path(d) / "prog.py"
        prog.write_text(program)
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(prog)],
                capture_output=True, timeout=spec.timeout_s, cwd=d,
            )
        except subprocess.TimeoutExpired:
            return GradeResult(False, 0.0, f"timed out after {spec.timeout_s}s")
        if proc.returncode == 0:
            return GradeResult(True, 1.0, "exec passed")
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        return GradeResult(False, 0.0, f"exit {proc.returncode}: {err[-1] if err else ''}"[:200])


_GRADERS = {
    "exact": _grade_exact,
    "contains": _grade_contains,
    "regex": _grade_regex,
    "numeric": _grade_numeric,
    "tool_call": _grade_tool_call,
    "json_schema": _grade_json_schema,
    "any": _grade_any,
    "exec": _grade_exec,
}
