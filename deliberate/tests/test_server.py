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
            "server": {"max_concurrent_requests": 8, "admission_wait_s": 5},
            "backends": {
                "base": {"endpoint": BACKEND, "model": "Qwen-Up", "profile": "qwen3"}
            },
            "profiles": {"qwen3": {"recover_tool_calls": True}},
        }
    )
    return TestClient(build_app(cfg))


def _completion(content=None, tool_calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "created": 1000,
        "model": "Qwen-Up",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
    }


def test_health_and_models():
    with make_client() as client:
        assert client.get("/health").json() == {"status": "ok"}
        models = client.get("/v1/models").json()
        ids = {m["id"] for m in models["data"]}
        assert "base" in ids and "base:high" in ids


@respx.mock
def test_non_stream_passthrough_no_tools():
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hi there")))
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "base", "messages": [{"role": "user", "content": "hello"}]},
        )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "hi there"
    assert resp.headers["x-deliberate-effort"] == "medium"
    assert resp.headers["x-deliberate-backend"] == "base"


@respx.mock
def test_upstream_receives_configured_model_not_client_alias():
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("ok")))
    with make_client() as client:
        client.post(
            "/v1/chat/completions",
            json={"model": "base:high", "messages": [{"role": "user", "content": "x"}]},
        )
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "Qwen-Up"            # upstream model, not "base:high"
    assert "reasoning_effort" not in sent
    assert sent["stream"] is False


@respx.mock
def test_effort_from_model_suffix_in_header():
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("ok")))
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "base:high", "messages": [{"role": "user", "content": "x"}]},
        )
    assert resp.headers["x-deliberate-effort"] == "high"


@respx.mock
def test_tool_call_recovery_non_stream():
    narrated = '<tool_call>{"name": "search", "arguments": {"q": "cats"}}</tool_call>'
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(narrated)))
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "base",
                "messages": [{"role": "user", "content": "find cats"}],
                "tools": [{"type": "function", "function": {"name": "search"}}],
            },
        )
    choice = resp.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    calls = choice["message"]["tool_calls"]
    assert calls[0]["function"]["name"] == "search"
    assert json.loads(calls[0]["function"]["arguments"]) == {"q": "cats"}


@respx.mock
def test_stream_passthrough_no_tools_forwards_bytes():
    sse = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, content=sse))
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "base",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    assert resp.status_code == 200
    assert b"[DONE]" in resp.content
    assert b'"content":"hi"' in resp.content


@respx.mock
def test_stream_with_tools_is_synthesized_with_recovered_calls():
    narrated = '<tool_call>{"name": "f", "arguments": {"a": 1}}</tool_call>'
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(narrated)))
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "base",
                "messages": [{"role": "user", "content": "go"}],
                "tools": [{"type": "function", "function": {"name": "f"}}],
                "stream": True,
            },
        )
    body = resp.content.decode()
    assert "[DONE]" in body
    assert '"tool_calls"' in body
    assert '"name": "f"' in body or '"name":"f"' in body


@respx.mock
def test_backend_error_is_propagated():
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad"}})
    )
    with make_client() as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "base", "messages": [{"role": "user", "content": "x"}]},
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "bad"


def test_rejects_body_without_messages():
    with make_client() as client:
        resp = client.post("/v1/chat/completions", json={"model": "base"})
    assert resp.status_code == 400
