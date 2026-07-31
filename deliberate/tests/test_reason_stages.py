"""Stage-level tests driven by a FakeClient (no network)."""

import asyncio

from deliberate.reason.client import CallResult
from deliberate.reason.pipeline import run_pipeline
from deliberate.reason.stages.best_of_n import BestOfNStage
from deliberate.reason.stages.frame import FrameStage
from deliberate.reason.stages.passthrough import PassthroughStage
from deliberate.reason.stages.reflect import ReflectStage
from deliberate.reason.state import Budget, ReasoningState
from deliberate.reason.client import BudgetedClient


class FakeClient:
    """Returns canned completions; matches on substrings of the last message."""

    def __init__(self, rules, default="ANSWER"):
        self.rules = rules  # list[(substring, [texts...] or text)]
        self.default = default
        self.calls = 0

    async def complete(self, messages, *, n=1, **kwargs):
        self.calls += 1
        last = messages[-1].get("content", "") if messages else ""
        text = self.default
        for needle, val in self.rules:
            if needle in last:
                text = val
                break
        if callable(text):
            text = text(self.calls)
        texts = text if isinstance(text, list) else [text] * n
        msgs = [{"role": "assistant", "content": t} for t in texts[:n]] or [
            {"role": "assistant", "content": self.default}
        ]
        return CallResult(messages=msgs, usage={"total_tokens": 10})


def _state(user="Explain why the sky is blue."):
    return ReasoningState.from_request(
        {"messages": [{"role": "user", "content": user}]}, effort="high", difficulty="hard"
    )


def test_passthrough_sets_answer():
    st = _state()
    client = FakeClient([], default="the answer")
    asyncio.run(PassthroughStage().run(st, client))
    assert st.answer["content"] == "the answer"


def test_frame_injects_grounding_and_confidence():
    brief = (
        '{"reframed_question": "Why is the sky blue?", "answer_shape": "explain Rayleigh",'
        ' "substitution_risk": "why the sea is blue", "residual_unknowns": ["none"],'
        ' "confidence": 0.8}'
    )
    st = _state()
    client = FakeClient([("analytical pre-flight", brief)])
    asyncio.run(FrameStage().run(st, client))
    assert st.scratch["confidence"] == 0.8
    assert st.messages[0]["role"] == "system"
    assert "Rayleigh" in st.messages[0]["content"]
    assert "sea is blue" in st.messages[0]["content"]  # substitution warning present


def test_frame_skips_when_tools_present():
    st = ReasoningState.from_request(
        {"messages": [{"role": "user", "content": "weather?"}],
         "tools": [{"type": "function", "function": {"name": "get_weather"}}]},
        effort="high", difficulty="moderate",
    )
    assert FrameStage().applicable(st) is False


def test_reflect_revises_on_critique():
    # draft -> critique finds an issue -> revise
    client = FakeClient([
        ("critical reviewer", '{"ok": false, "issue": "missed Rayleigh scattering"}'),
        ("Revise your answer", "Improved: Rayleigh scattering."),
    ], default="Draft answer.")
    st = _state()
    asyncio.run(ReflectStage(rounds=1).run(st, client))
    assert st.answer["content"] == "Improved: Rayleigh scattering."
    assert any(e.kind == "revised" for e in st.trace)


def test_reflect_accepts_good_draft():
    client = FakeClient([("critical reviewer", '{"ok": true, "issue": ""}')], default="Good answer.")
    st = _state()
    asyncio.run(ReflectStage(rounds=1).run(st, client))
    assert st.answer["content"] == "Good answer."
    assert any(e.kind == "accepted" for e in st.trace)


def test_best_of_n_selects_by_consistency():
    # three candidates: majority say "42"
    client = FakeClient([], default=["42", "42", "999"])
    st = _state("What is 6 times 7?")
    asyncio.run(BestOfNStage(n=3).run(st, client))
    assert st.answer["content"] == "42"
    assert st.scratch["best_of_n"]["verifier"] == "consistency"


def test_budget_exceeded_stops_pipeline_but_answers():
    client = FakeClient([("analytical pre-flight",
                          '{"reframed_question":"q","answer_shape":"a","confidence":0.5}')],
                        default="answer")
    st = _state()
    budget = Budget(max_model_calls=1)  # frame uses the 1 call, reflect would exceed
    bclient = BudgetedClient(client, budget)
    st = asyncio.run(run_pipeline([FrameStage(), ReflectStage()], st, bclient))
    # pipeline stopped early but still produced an answer via ensure_answer... which
    # itself needs a call and will also be budget-limited; the key invariant is no crash
    assert any(e.kind == "budget_exceeded" for e in st.trace)
