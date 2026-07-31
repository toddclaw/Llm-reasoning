"""Reasoning state — the working memory a pipeline evolves for one request.

Held outside the model (the "System 2 externalises state" idea from the design):
stages read and write ``messages``, ``scratch`` and ``answer``, and append to
``trace``. Everything a stage needs is here; nothing leaks between requests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

Message = dict[str, Any]


class BudgetExceeded(Exception):
    """Raised when a request runs out of model-call / token budget."""


@dataclass
class Budget:
    max_model_calls: int = 12
    max_tokens: int = 200_000
    model_calls: int = 0
    tokens: int = 0

    def charge(self, calls: int, tokens: int) -> None:
        self.model_calls += calls
        self.tokens += tokens
        if self.model_calls > self.max_model_calls:
            raise BudgetExceeded(f"model calls {self.model_calls} > {self.max_model_calls}")
        if self.tokens > self.max_tokens:
            raise BudgetExceeded(f"tokens {self.tokens} > {self.max_tokens}")


@dataclass
class TraceEvent:
    stage: str
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class ReasoningState:
    request: dict[str, Any]          # the original OpenAI request (untouched)
    messages: list[Message]          # working conversation the stages evolve
    tools: list[dict] | None = None
    response_format: dict | None = None
    answer: Message | None = None    # the current best assistant message
    scratch: dict[str, Any] = field(default_factory=dict)
    trace: list[TraceEvent] = field(default_factory=list)
    effort: str = "medium"
    difficulty: str = "moderate"

    def log(self, stage: str, kind: str, **data: Any) -> None:
        self.trace.append(TraceEvent(stage=stage, kind=kind, data=data))

    @property
    def has_tools(self) -> bool:
        return bool(self.tools)

    @property
    def confidence(self) -> float | None:
        c = self.scratch.get("confidence")
        return float(c) if isinstance(c, (int, float)) else None

    @staticmethod
    def from_request(request: dict[str, Any], *, effort: str, difficulty: str) -> "ReasoningState":
        return ReasoningState(
            request=request,
            messages=list(request.get("messages", [])),
            tools=request.get("tools"),
            response_format=request.get("response_format"),
            effort=effort,
            difficulty=difficulty,
        )
