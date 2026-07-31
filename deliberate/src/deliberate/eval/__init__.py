"""Deliberate eval harness (Phase 1).

Turns "does the layer help?" into a repeatable number: run a suite of tasks across
targets (base model vs base+layer), grade deterministically, and report lift with a
variance band. Fully offline-testable via a scripted runner; runs against a live
endpoint from the CLI.
"""

from __future__ import annotations

from .cache import ResponseCache
from .graders import GradeResult, grade
from .harness import run_suite
from .metrics import (
    Lift,
    Row,
    TargetSummary,
    brier_score,
    compute_lift,
    expected_calibration_error,
    summarize,
)
from .report import render_html, render_text
from .runner import (
    Completion,
    DirectRunner,
    ProxyRunner,
    ReasonRunner,
    ScriptedRunner,
    CachingRunner,
    build_backend_runner,
)
from .task import GradeSpec, RequestSpec, Task, load_suite, load_task

__all__ = [
    "ResponseCache",
    "GradeResult",
    "grade",
    "run_suite",
    "Lift",
    "Row",
    "TargetSummary",
    "brier_score",
    "compute_lift",
    "expected_calibration_error",
    "summarize",
    "render_html",
    "render_text",
    "Completion",
    "DirectRunner",
    "ProxyRunner",
    "ReasonRunner",
    "ScriptedRunner",
    "CachingRunner",
    "build_backend_runner",
    "GradeSpec",
    "RequestSpec",
    "Task",
    "load_suite",
    "load_task",
]
