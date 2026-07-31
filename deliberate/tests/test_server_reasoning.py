import json

import httpx
import respx
from fastapi.testclient import TestClient

from deliberate.config import Config
from deliberate.server import build_app

BACKEND = "http://rack.test/v1"
CHAT_URL = f"{BACKEND}/chat/completions"


def make_client() -> TestClient:
    cfg = Config.model_validate(
        {
            "backends": {"base": {"endpoint": BACKEND, "model": "Qwen-Up", "profile": "qwen3"}},
            "profiles": {"qwen3": {}},
        }
    )
    return TestClient(build_app(cfg))


def _completion(content):
    return {
        "id": "c", "object": "chat.completion", "created": 1, "model": "Qwen-Up",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


def _responder(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    last = body["messages"][-1]["content"]
    if "analytical pre-flight" in last:
        return httpx.Response(200, json=_completion(
            '{"reframed_question":"why sky is blue","answer_shape":"explain Rayleigh",'
            '"substitution_risk":"","residual_unknowns":[],"confidence":0.72}'))
    if "Break the task" in last:
        return httpx.Response(200, json=_completion('{"steps":["recall Rayleigh","explain"]}'))
    if "critical reviewer" in last or "Check the answer" in last:
        return httpx.Response(200, json=_completion('{"ok": true, "issue": ""}'))
    return httpx.Response(200, json=_completion("FINAL ANSWER"))


@respx.mock
def test_effort_off_is_passthrough_single_call():
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("FINAL ANSWER")))
    with make_client() as client:
        resp = client.post("/v1/chat/completions", json={
            "model": "base:off",
            "messages": [{"role": "user", "content": "Explain why the sky is blue in detail."}],
        })
    assert resp.status_code == 200
    assert resp.headers["x-deliberate-stages"] == "passthrough"
    assert resp.json()["choices"][0]["message"]["content"] == "FINAL ANSWER"
    assert route.call_count == 1


@respx.mock
def test_high_effort_runs_reasoning_pipeline():
    respx.post(CHAT_URL).mock(side_effect=_responder)
    with make_client() as client:
        resp = client.post("/v1/chat/completions", json={
            "model": "base:high",
            "messages": [{"role": "user", "content": "Explain why the sky appears blue during the day."}],
        })
    assert resp.status_code == 200
    stages = resp.headers["x-deliberate-stages"]
    assert "frame" in stages and "reflect" in stages
    assert resp.headers["x-deliberate-difficulty"] == "hard"
    # frame produced a calibrated confidence, surfaced as a header
    assert resp.headers["x-deliberate-confidence"] == "0.72"
    assert resp.json()["choices"][0]["message"]["content"] == "FINAL ANSWER"


@respx.mock
def test_reasoning_still_recovers_tool_calls_via_passthrough():
    # tool requests classify to a pipeline that mostly skips (frame/reflect skip on tools);
    # the answer is produced by ensure_answer through the adapter, recovering narrated calls.
    narrated = '<tool_call>{"name": "get_weather", "arguments": {"city": "Paris"}}</tool_call>'
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(narrated)))
    with make_client() as client:
        resp = client.post("/v1/chat/completions", json={
            "model": "base:high",
            "messages": [{"role": "user", "content": "What's the weather in Paris? Use the tool."}],
            "tools": [{"type": "function", "function": {"name": "get_weather"}}],
        })
    msg = resp.json()["choices"][0]["message"]
    assert msg.get("tool_calls"), "tool call should be recovered even on the reasoning path"
    assert msg["tool_calls"][0]["function"]["name"] == "get_weather"
