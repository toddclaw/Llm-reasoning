"""Run a suite of tasks across a set of targets and collect scored rows.

``run_suite`` is the core: for each (target × task × seed) it produces a completion,
grades it deterministically, and records a Row. It is runner-agnostic, so tests
drive it with a ScriptedRunner and the CLI drives it with real Direct/Proxy runners
against a live endpoint. Concurrency is bounded so a fleet of calls doesn't stampede
the backend.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .graders import grade
from .metrics import Row, cost_of
from .runner import Runner
from .task import Task


async def run_suite(
    targets: list[Runner],
    tasks: list[Task],
    seeds: list[int] | None = None,
    *,
    concurrency: int = 4,
    pricing: dict[str, dict[str, float]] | None = None,
) -> list[Row]:
    seeds = seeds or [0]
    pricing = pricing or {}
    sem = asyncio.Semaphore(concurrency)
    rows: list[Row] = []

    async def one(target: Runner, task: Task, seed: int) -> None:
        async with sem:
            completion = await target.run(task.request.to_request(), seed)
        result = grade(task, completion)
        price = pricing.get(target.model)
        rows.append(
            Row(
                target=target.name,
                task_id=task.id,
                kind=task.kind,
                seed=seed,
                passed=result.passed,
                score=result.score,
                tool_call_valid=result.tool_call_valid,
                latency_ms=completion.latency_ms,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                cost_usd=cost_of(completion.prompt_tokens, completion.completion_tokens, price),
                error=completion.error,
            )
        )

    await asyncio.gather(
        *(one(t, task, s) for t in targets for task in tasks for s in seeds)
    )
    # Deterministic order for stable reports.
    rows.sort(key=lambda r: (r.target, r.task_id, r.seed))
    return rows
