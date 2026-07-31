"""The `plan_act_verify` stage — decompose, solve stepwise, then self-verify.

A single-turn version: it does NOT drive the client's external tool loop (that stays
with the caller — the single-turn boundary), so it targets reasoning tasks where the
work is internal (math, logic, multi-constraint analysis). Decompose into steps,
work them in order accumulating a scratchpad, produce an answer, then run one
verification pass that can trigger a single correction.
"""

from __future__ import annotations

from ..client import ModelClient
from ..state import ReasoningState
from ..util import extract_json_object

_PLAN_PROMPT = """Break the task below into a short ordered list of concrete steps \
needed to solve it correctly. Reply with ONLY JSON: {{"steps": ["...", "..."]}} \
(at most {max_steps} steps).

Task:
{question}
"""

_SOLVE_PROMPT = """Work through the task step by step using this plan, showing your \
reasoning, then give the final answer clearly at the end.

Plan:
{plan}
"""

_VERIFY_PROMPT = """Check the answer below against the task for errors in reasoning or \
arithmetic. Reply with ONLY JSON: {{"ok": <true|false>, "issue": "<problem or empty>"}}.

Task:
{question}

Answer:
{answer}
"""


class PlanActVerifyStage:
    id = "plan_act_verify"

    def __init__(self, max_steps: int = 6) -> None:
        self.max_steps = max_steps

    def applicable(self, state: ReasoningState) -> bool:
        return not state.has_tools

    async def run(self, state: ReasoningState, client: ModelClient) -> None:
        question = _first_user_text(state)

        plan_res = await client.complete(
            [{"role": "user", "content": _PLAN_PROMPT.format(question=question, max_steps=self.max_steps)}],
            temperature=0.2,
        )
        plan = (extract_json_object(plan_res.text) or {}).get("steps") or []
        plan_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan[: self.max_steps])) or "(solve directly)"

        solve_msgs = state.messages + [{"role": "user", "content": _SOLVE_PROMPT.format(plan=plan_text)}]
        solved = await client.complete(solve_msgs, temperature=0.2)
        if solved.error is None and solved.text.strip():
            state.answer = solved.message
        state.log(self.id, "planned", steps=len(plan))

        # one verification + correction pass
        answer_text = state.answer.get("content") or "" if state.answer else ""
        if not answer_text:
            return
        check = await client.complete(
            [{"role": "user", "content": _VERIFY_PROMPT.format(question=question, answer=answer_text)}],
            temperature=0.0,
        )
        verdict = extract_json_object(check.text) or {}
        if verdict.get("ok") is False and verdict.get("issue"):
            fix_msgs = solve_msgs + [
                {"role": "assistant", "content": answer_text},
                {"role": "user", "content": f"Fix this problem and give the corrected answer: {verdict['issue']}"},
            ]
            fixed = await client.complete(fix_msgs, temperature=0.1)
            if fixed.error is None and fixed.text.strip():
                state.answer = fixed.message
                state.log(self.id, "corrected", issue=str(verdict["issue"])[:120])


def _first_user_text(state: ReasoningState) -> str:
    for m in reversed(state.messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""
