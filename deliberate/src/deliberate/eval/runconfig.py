"""Bench run configuration: which targets to compare, seeds, pricing, cache.

Targets are the systems under test — typically one ``direct`` (base model) and one
``proxy`` (base + Deliberate adapter) pointed at the *same* upstream model so the
lift is attributable to the layer. ``${ENV}`` references in the YAML are expanded
from the environment, so API keys stay out of the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from ..config import BackendConfig
from .cache import ResponseCache
from .runner import CachingRunner, Runner, build_backend_runner

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _interpolate(obj: Any) -> Any:
    if isinstance(obj, str):
        def repl(m: re.Match[str]) -> str:
            var = m.group(1)
            val = os.environ.get(var)
            if val is None:
                raise KeyError(f"config references ${{{var}}} but it is not set in the environment")
            return val
        return _ENV_RE.sub(repl, obj)
    if isinstance(obj, dict):
        return {k: _interpolate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate(v) for v in obj]
    return obj


class TargetSpec(BaseModel):
    name: str
    mode: Literal["direct", "proxy", "reason"]
    backend: BackendConfig
    # only for mode: reason — the explicit pipeline to run
    stages: list[str] = Field(default_factory=list)
    stage_params: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BenchConfig(BaseModel):
    targets: list[TargetSpec]
    base: str | None = None  # target name to treat as the baseline for lift
    layer: str | None = None  # target name to treat as the layer for lift
    seeds: int | list[int] = 1
    concurrency: int = 4
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    cache_dir: str | None = ".deliberate_cache"

    def seed_list(self) -> list[int]:
        if isinstance(self.seeds, int):
            return list(range(self.seeds))
        return list(self.seeds)

    def lift_pair(self) -> tuple[str, str] | None:
        names = [t.name for t in self.targets]
        base = self.base or (names[0] if names else None)
        layer = self.layer or (names[1] if len(names) > 1 else None)
        if base and layer and base != layer:
            return layer, base
        return None


def load_bench_config(path: str | Path) -> BenchConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return BenchConfig.model_validate(_interpolate(data))


def build_runners(cfg: BenchConfig, cache: ResponseCache) -> list[Runner]:
    runners: list[Runner] = []
    for t in cfg.targets:
        runner = build_backend_runner(t.name, t.mode, t.backend, t.stages, t.stage_params)
        runners.append(CachingRunner(runner, cache))
    return runners
