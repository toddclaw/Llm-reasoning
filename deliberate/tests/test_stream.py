import json

from deliberate.stream import synthesize_sse


def _data_lines(chunks):
    out = []
    for c in chunks:
        assert c.startswith("data: ")
        payload = c[len("data: ") :].strip()
        if payload == "[DONE]":
            out.append("[DONE]")
        else:
            out.append(json.loads(payload))
    return out


def test_synthesize_streams_content_then_done():
    response = {
        "id": "chatcmpl-1",
        "created": 1000,
        "model": "m",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "hello"},
             "finish_reason": "stop"}
        ],
    }
    lines = _data_lines(list(synthesize_sse(response)))
    assert lines[-1] == "[DONE]"
    # role delta, content delta, terminal delta
    assert lines[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert any(l != "[DONE]" and l["choices"][0]["delta"].get("content") == "hello" for l in lines)
    assert lines[-2]["choices"][0]["finish_reason"] == "stop"


def test_synthesize_emits_tool_calls_with_index():
    response = {
        "id": "chatcmpl-2",
        "created": 1000,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_a", "type": "function",
                         "function": {"name": "f", "arguments": "{}"}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    lines = _data_lines(list(synthesize_sse(response)))
    tool_deltas = [
        l for l in lines
        if l != "[DONE]" and l["choices"][0]["delta"].get("tool_calls")
    ]
    assert len(tool_deltas) == 1
    call = tool_deltas[0]["choices"][0]["delta"]["tool_calls"][0]
    assert call["index"] == 0
    assert call["function"]["name"] == "f"
    assert lines[-2]["choices"][0]["finish_reason"] == "tool_calls"
