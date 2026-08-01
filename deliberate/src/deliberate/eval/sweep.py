"""Sweeps and ablations (Phase 3).

A sweep runs many pipeline *variants* against one suite on one model, so you can see
which stages help and by how much, and promote to the default only what clears the
band. Variants come from three sources, freely combined:

  * explicit ``variants``
  * ``ablation`` — a stage list expanded to build-up (prefixes) + leave-one-out
  * ``grid`` — vary one stage parameter over a set of values

Everything shares the baseline's model, so a variant's lift is attributable to the
stages, not the weights.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ..config import BackendConfig
from .cache import ResponseCache
from .metrics import Row, SweepAnalysis, TargetSummary, analyze_sweep, summarize
from .runner import CachingRunner, Runner, build_backend_runner
from .runconfig import _interpolate  # reuse ${ENV} expansion
from .harness import run_suite
from .task import Task, load_suite


class VariantSpec(BaseModel):
    name: str
    mode: str = "reason"  # reason | proxy | direct
    stages: list[str] = Field(default_factory=list)
    stage_params: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.mode, tuple(self.stages), tuple(sorted(
            (k, tuple(sorted(v.items()))) for k, v in self.stage_params.items()
        )))


class GridSpec(BaseModel):
    stage: str
    param: str
    values: list[Any]
    base_stages: list[str] = Field(default_factory=list)


class SweepSpec(BaseModel):
    suite: str
    backend: BackendConfig
    baseline_mode: str = "direct"
    baseline_stages: list[str] = Field(default_factory=list)
    baseline_name: str = "base"
    seeds: int | list[int] = 3
    concurrency: int = 4
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    cache_dir: str | None = ".deliberate_cache"
    variants: list[VariantSpec] = Field(default_factory=list)
    ablation: list[str] = Field(default_factory=list)
    grid: GridSpec | None = None

    def seed_list(self) -> list[int]:
        return list(range(self.seeds)) if isinstance(self.seeds, int) else list(self.seeds)

    def expand(self) -> list[VariantSpec]:
        out: list[VariantSpec] = list(self.variants)
        out.extend(_expand_ablation(self.ablation))
        if self.grid is not None:
            out.extend(_expand_grid(self.grid))
        # dedupe by pipeline identity, keep first name; drop any that equal the baseline
        seen: set[tuple] = set()
        base_key = (self.baseline_mode, tuple(self.baseline_stages), ())
        result: list[VariantSpec] = []
        for v in out:
            if v.key in seen or v.key == base_key:
                continue
            seen.add(v.key)
            result.append(v)
        return result


def _expand_ablation(stages: list[str]) -> list[VariantSpec]:
    if not stages:
        return []
    variants: list[VariantSpec] = []
    # build-up: prefixes show the marginal value of adding each stage in order
    for i in range(len(stages) + 1):
        prefix = stages[:i]
        name = "buildup:" + ("+".join(prefix) if prefix else "passthrough")
        variants.append(VariantSpec(name=name, stages=prefix))
    # leave-one-out: each stage's marginal value given the others
    if len(stages) > 1:
        for i, stage in enumerate(stages):
            loo = stages[:i] + stages[i + 1 :]
            variants.append(VariantSpec(name=f"no_{stage}", stages=loo))
    return variants


def _expand_grid(grid: GridSpec) -> list[VariantSpec]:
    variants: list[VariantSpec] = []
    stages = grid.base_stages or [grid.stage]
    for val in grid.values:
        variants.append(
            VariantSpec(
                name=f"{grid.stage}.{grid.param}={val}",
                stages=stages,
                stage_params={grid.stage: {grid.param: val}},
            )
        )
    return variants


def load_sweep_spec(path: str | Path) -> SweepSpec:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return SweepSpec.model_validate(_interpolate(data))


def build_sweep_runners(spec: SweepSpec, cache: ResponseCache) -> list[Runner]:
    runners: list[Runner] = [
        CachingRunner(
            build_backend_runner(spec.baseline_name, spec.baseline_mode, spec.backend,
                                 spec.baseline_stages),
            cache,
        )
    ]
    for v in spec.expand():
        runners.append(
            CachingRunner(
                build_backend_runner(v.name, v.mode, spec.backend, v.stages, v.stage_params),
                cache,
            )
        )
    return runners


async def run_sweep(spec: SweepSpec) -> tuple[list[Row], dict[str, TargetSummary], SweepAnalysis]:
    tasks: list[Task] = load_suite(spec.suite)
    cache = ResponseCache(spec.cache_dir)
    runners = build_sweep_runners(spec, cache)
    try:
        rows = await run_suite(
            runners, tasks, spec.seed_list(),
            concurrency=spec.concurrency, pricing=spec.pricing,
        )
    finally:
        for r in runners:
            close = getattr(r, "aclose", None)
            if close is not None:
                await close()
    summaries = summarize(rows)
    analysis = analyze_sweep(summaries, spec.baseline_name)
    return rows, summaries, analysis
