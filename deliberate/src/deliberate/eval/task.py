"""Eval task format and loader.

A task is a self-contained unit the harness can score deterministically: a request
to send, and a grade spec that says what a correct answer looks like. Tasks live as
YAML files; a suite is a directory of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class GradeSpec(BaseModel):
    """How to score a completion. Deterministic graders only in Phase 1."""

    type: Literal[
        "exact", "contains", "regex", "numeric", "tool_call", "json_schema", "any"
    ]
    # exact / contains / regex
    expected: Any | None = None
    ignore_case: bool = True
    strip: bool = True
    # numeric
    tolerance: float = 0.0
    # tool_call
    expected_name: str | None = None
    expected_args: dict[str, Any] | None = None  # subset match against parsed args
    # json_schema (aliased so YAML can say `schema:`)
    schema_def: dict[str, Any] | None = Field(default=None, alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class RequestSpec(BaseModel):
    """The OpenAI-style request to send (model is supplied by the runner)."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    response_format: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    def to_request(self) -> dict[str, Any]:
        out: dict[str, Any] = {"messages": self.messages}
        for key in ("tools", "tool_choice", "response_format", "temperature", "max_tokens"):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        return out


class Task(BaseModel):
    id: str
    kind: str = "qa"  # qa | tool | structured | transparency | substitution | ...
    difficulty: int = 1
    tags: list[str] = Field(default_factory=list)
    request: RequestSpec
    grade: GradeSpec

    @property
    def has_tools(self) -> bool:
        return bool(self.request.tools)


def load_task(path: str | Path) -> Task:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: task file must be a YAML mapping")
    return Task.model_validate(data)


def load_suite(directory: str | Path) -> list[Task]:
    """Load every ``*.yaml`` task under ``directory`` (sorted by id)."""
    d = Path(directory)
    if not d.is_dir():
        raise NotADirectoryError(f"suite dir not found: {directory}")
    tasks = [load_task(p) for p in sorted(d.glob("*.yaml"))]
    ids = [t.id for t in tasks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate task ids in suite: {sorted(dupes)}")
    if not tasks:
        raise ValueError(f"no tasks found in {directory}")
    return tasks
