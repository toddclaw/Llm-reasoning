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
    SweepAnalysis,
    TargetSummary,
    VariantVerdict,
    analyze_sweep,
    brier_score,
    compute_lift,
    expected_calibration_error,
    summarize,
)
from .report import render_html, render_sweep_html, render_sweep_text, render_text
from .sweep import SweepSpec, load_sweep_spec, run_sweep
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
    "SweepAnalysis",
    "TargetSummary",
    "VariantVerdict",
    "analyze_sweep",
    "brier_score",
    "compute_lift",
    "expected_calibration_error",
    "summarize",
    "render_html",
    "render_sweep_html",
    "render_sweep_text",
    "render_text",
    "SweepSpec",
    "load_sweep_spec",
    "run_sweep",
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
