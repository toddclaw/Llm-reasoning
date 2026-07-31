"""Identity stage: produce an answer with no extra reasoning."""

from __future__ import annotations

from ..client import ModelClient
from ..pipeline import ensure_answer
from ..state import ReasoningState


class PassthroughStage:
    id = "passthrough"

    def applicable(self, state: ReasoningState) -> bool:
        return True

    async def run(self, state: ReasoningState, client: ModelClient) -> None:
        await ensure_answer(state, client)
