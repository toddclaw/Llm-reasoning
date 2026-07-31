"""Effort × difficulty → pipeline resolution, and the stage factory.

The routing table is configuration (docs/deliberate/01-architecture.md §3): it is the
primary thing tuned by the eval harness. Defaults are conservative — deliberation
scales with both the caller's effort and the inferred difficulty, and ``off`` /
trivial always resolve to passthrough so easy traffic stays fast.
"""

from __future__ import annotations

from typing import Any

from .pipeline import Stage
from .stages.best_of_n import BestOfNStage
from .stages.frame import FrameStage
from .stages.passthrough import PassthroughStage
from .stages.plan_act_verify import PlanActVerifyStage
from .stages.reflect import ReflectStage

# effort.difficulty -> ordered stage ids
DEFAULT_ROUTES: dict[str, list[str]] = {
    "off.trivial": [], "off.moderate": [], "off.hard": [],
    "low.trivial": [], "low.moderate": ["frame", "reflect"], "low.hard": ["frame", "reflect"],
    "medium.trivial": [], "medium.moderate": ["frame", "reflect"],
    "medium.hard": ["frame", "plan_act_verify", "reflect"],
    "high.trivial": ["frame", "reflect"],
    "high.moderate": ["frame", "best_of_n", "reflect"],
    "high.hard": ["frame", "plan_act_verify", "best_of_n", "reflect"],
}

DEFAULT_STAGE_PARAMS: dict[str, dict[str, Any]] = {
    "best_of_n": {"n": 4, "temperature": 0.7, "selector": "auto"},
    "reflect": {"rounds": 1},
    "plan_act_verify": {"max_steps": 6},
}


def build_stages(
    stage_ids: list[str], stage_params: dict[str, dict[str, Any]] | None = None
) -> list[Stage]:
    """Build a concrete stage list from ids (used by the eval ReasonRunner)."""
    params = {**DEFAULT_STAGE_PARAMS, **(stage_params or {})}
    return [_build_stage(sid, params.get(sid, {})) for sid in stage_ids]


def _build_stage(stage_id: str, params: dict[str, Any]) -> Stage:
    if stage_id == "passthrough":
        return PassthroughStage()
    if stage_id == "frame":
        return FrameStage()
    if stage_id == "reflect":
        return ReflectStage(**params)
    if stage_id == "best_of_n":
        return BestOfNStage(**params)
    if stage_id == "plan_act_verify":
        return PlanActVerifyStage(**params)
    raise ValueError(f"unknown stage id: {stage_id!r}")


class PipelineFactory:
    """Resolves (effort, difficulty) to a concrete list of stages."""

    def __init__(
        self,
        routes: dict[str, list[str]] | None = None,
        stage_params: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.routes = {**DEFAULT_ROUTES, **(routes or {})}
        self.stage_params = {**DEFAULT_STAGE_PARAMS, **(stage_params or {})}

    def stage_ids(self, effort: str, difficulty: str) -> list[str]:
        return self.routes.get(f"{effort}.{difficulty}", [])

    def build(self, effort: str, difficulty: str) -> list[Stage]:
        ids = self.stage_ids(effort, difficulty)
        return [_build_stage(sid, self.stage_params.get(sid, {})) for sid in ids]
