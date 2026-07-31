"""Stage protocol and the pipeline runner.

A pipeline is an ordered list of stages applied to a ReasoningState. Each stage is
skippable (``applicable``), budget-aware, and degrades gracefully: if the budget is
exhausted, the pipeline stops and returns the best answer so far rather than failing.
"""

from __future__ import annotations

from typing import Protocol

from .client import ModelClient
from .state import BudgetExceeded, Message, ReasoningState


class Stage(Protocol):
    id: str

    def applicable(self, state: ReasoningState) -> bool: ...

    async def run(self, state: ReasoningState, client: ModelClient) -> None: ...


async def ensure_answer(state: ReasoningState, client: ModelClient) -> Message:
    """Guarantee ``state.answer`` is set by asking the model with current messages."""
    if state.answer is not None:
        return state.answer
    result = await client.complete(
        state.messages, tools=state.tools, response_format=state.response_format
    )
    state.answer = result.message if result.error is None else {
        "role": "assistant", "content": "", "_error": result.error,
    }
    return state.answer


async def run_pipeline(
    stages: list[Stage], state: ReasoningState, client: ModelClient
) -> ReasoningState:
    for stage in stages:
        if not stage.applicable(state):
            state.log(stage.id, "skipped")
            continue
        try:
            await stage.run(state, client)
            state.log(stage.id, "ran")
        except BudgetExceeded as exc:
            state.log(stage.id, "budget_exceeded", detail=str(exc))
            break
    # Guarantee an answer, but never let a budget wall crash the request.
    try:
        await ensure_answer(state, client)
    except BudgetExceeded as exc:
        state.log("pipeline", "budget_exceeded_final", detail=str(exc))
        if state.answer is None:
            state.answer = {"role": "assistant", "content": "",
                            "_deliberate": "budget exhausted before an answer was produced"}
    return state
