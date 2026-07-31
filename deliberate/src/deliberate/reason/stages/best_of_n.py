"""The `best_of_n` stage — sample N candidates, select via a verifier or judge.

Cheap on an abundant backend; the verifier is what makes the selection trustworthy.
Prefers a deterministic check (valid tool call / valid JSON / consistency) and only
falls back to a judge model when nothing structural applies.
"""

from __future__ import annotations

from ..client import ModelClient
from ..state import ReasoningState
from ..verifiers import select_best


class BestOfNStage:
    id = "best_of_n"

    def __init__(self, n: int = 4, temperature: float = 0.7, selector: str = "auto") -> None:
        self.n = max(1, n)
        self.temperature = temperature
        self.selector = selector

    def applicable(self, state: ReasoningState) -> bool:
        return self.n > 1

    async def run(self, state: ReasoningState, client: ModelClient) -> None:
        result = await client.complete(
            state.messages,
            tools=state.tools,
            response_format=state.response_format,
            temperature=self.temperature,
            n=self.n,
            seed=0,
        )
        if result.error is not None or not result.messages:
            state.log(self.id, "no_candidates", error=result.error)
            return
        selection = await select_best(
            result.messages,
            client=client,
            question=_first_user_text(state),
            tools=state.tools,
            response_format=state.response_format,
            selector=self.selector,
        )
        state.answer = selection.message
        state.scratch["best_of_n"] = {
            "n": len(result.messages),
            "verifier": selection.verifier,
            "passing": selection.passing,
        }
        state.log(self.id, "selected", n=len(result.messages),
                  verifier=selection.verifier, passing=selection.passing)


def _first_user_text(state: ReasoningState) -> str:
    for m in reversed(state.messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""
