"""Deliberate reasoning layer (Phase 2).

Composable reasoning *stages* applied to one request, selected by effort × difficulty:
``frame`` (Inquiry & Debiasing), ``plan_act_verify``, ``best_of_n``, ``reflect``, and
``passthrough``. State lives outside the model; stages call a ``ModelClient``.
"""

from __future__ import annotations

from .classify import classify_difficulty
from .client import BackendModelClient, BudgetedClient, CallResult, ModelClient
from .pipeline import Stage, ensure_answer, run_pipeline
from .routing import PipelineFactory
from .state import Budget, BudgetExceeded, ReasoningState, TraceEvent

__all__ = [
    "classify_difficulty",
    "BackendModelClient",
    "BudgetedClient",
    "CallResult",
    "ModelClient",
    "Stage",
    "ensure_answer",
    "run_pipeline",
    "PipelineFactory",
    "Budget",
    "BudgetExceeded",
    "ReasoningState",
    "TraceEvent",
]
