import asyncio

from deliberate.reason import PipelineFactory, classify_difficulty
from deliberate.reason.client import CallResult
from deliberate.reason.pipeline import run_pipeline
from deliberate.reason.routing import build_stages
from deliberate.reason.state import ReasoningState


class FakeClient:
    def __init__(self, brief_conf=0.7):
        self.brief_conf = brief_conf
        self.calls = 0

    async def complete(self, messages, *, n=1, **kwargs):
        self.calls += 1
        last = messages[-1].get("content", "")
        if "analytical pre-flight" in last:
            text = f'{{"reframed_question":"q","answer_shape":"a","confidence":{self.brief_conf}}}'
        elif "critical reviewer" in last:
            text = '{"ok": true, "issue": ""}'
        else:
            text = "final answer"
        return CallResult(messages=[{"role": "assistant", "content": text}] * n,
                          usage={"total_tokens": 5})


def test_classifier_levels():
    assert classify_difficulty([{"role": "user", "content": "hi"}]) == "trivial"
    assert classify_difficulty([{"role": "user", "content": "Prove that sqrt(2) is irrational."}]) == "hard"
    assert classify_difficulty(
        [{"role": "user", "content":
          "Write a short friendly greeting message for a new user joining our community forum today."}]
    ) == "moderate"


def test_routing_off_and_trivial_are_passthrough():
    f = PipelineFactory()
    assert f.stage_ids("off", "hard") == []
    assert f.stage_ids("medium", "trivial") == []
    assert f.stage_ids("high", "hard") == ["frame", "plan_act_verify", "best_of_n", "reflect"]


def test_routing_override_from_config():
    f = PipelineFactory(routes={"medium.moderate": ["frame"]})
    assert f.stage_ids("medium", "moderate") == ["frame"]


def test_pipeline_frame_then_reflect_produces_answer_with_confidence():
    stages = build_stages(["frame", "reflect"])
    st = ReasoningState.from_request(
        {"messages": [{"role": "user", "content": "Explain Rayleigh scattering."}]},
        effort="high", difficulty="hard",
    )
    client = FakeClient(brief_conf=0.65)
    st = asyncio.run(run_pipeline(stages, st, client))
    assert st.answer["content"] == "final answer"
    assert st.confidence == 0.65
    # frame ran (system message injected), reflect accepted
    assert st.messages[0]["role"] == "system"
    assert any(e.stage == "frame" and e.kind == "brief" for e in st.trace)


def test_empty_pipeline_still_answers():
    st = ReasoningState.from_request(
        {"messages": [{"role": "user", "content": "hi"}]}, effort="off", difficulty="trivial"
    )
    st = asyncio.run(run_pipeline([], st, FakeClient()))
    assert st.answer["content"] == "final answer"
