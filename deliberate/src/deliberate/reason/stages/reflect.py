"""The `reflect` stage — draft, critique with fresh context, revise.

The critic never sees the drafting rationale (it gets only the question + the draft),
so it doesn't rubber-stamp. Cheap and broadly useful. Skipped for tool-dispatch turns.
"""

from __future__ import annotations

from ..client import ModelClient
from ..pipeline import ensure_answer
from ..state import ReasoningState
from ..util import extract_json_object

_CRITIQUE_PROMPT = """You are a critical reviewer. You are given a question and a \
draft answer written by someone else. Find the most important error, gap, or \
unsupported claim. Reply with ONLY a JSON object:
{{"ok": <true|false>, "issue": "<the single most important problem, or empty>"}}

Question:
{question}

Draft answer:
{draft}
"""

_REVISE_PROMPT = """Revise your answer to fix this issue, keeping everything that was \
correct. Issue: {issue}

Reply with the improved answer only."""


class ReflectStage:
    id = "reflect"

    def __init__(self, rounds: int = 1) -> None:
        self.rounds = rounds

    def applicable(self, state: ReasoningState) -> bool:
        return not state.has_tools

    async def run(self, state: ReasoningState, client: ModelClient) -> None:
        await ensure_answer(state, client)
        question = _first_user_text(state)

        for r in range(self.rounds):
            draft = state.answer.get("content") or "" if state.answer else ""
            if not draft:
                return
            crit = await client.complete(
                [{"role": "user", "content": _CRITIQUE_PROMPT.format(question=question, draft=draft)}],
                temperature=0.0,
            )
            verdict = extract_json_object(crit.text) or {}
            if verdict.get("ok") is True or not verdict.get("issue"):
                state.log(self.id, "accepted", round=r)
                return
            issue = str(verdict["issue"])
            revise_msgs = state.messages + [
                {"role": "assistant", "content": draft},
                {"role": "user", "content": _REVISE_PROMPT.format(issue=issue)},
            ]
            revised = await client.complete(revise_msgs, temperature=0.2)
            if revised.error is None and revised.text.strip():
                state.answer = revised.message
                state.log(self.id, "revised", round=r, issue=issue[:120])


def _first_user_text(state: ReasoningState) -> str:
    for m in reversed(state.messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""
