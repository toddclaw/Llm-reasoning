import json

from deliberate.adapt.qwen import QwenProfile, recover_tool_calls, _tool_call_pattern
from deliberate.config import ProfileConfig


def _pat():
    return _tool_call_pattern(["tool_call"])


def test_recovers_single_narrated_tool_call():
    content = (
        "Let me check that.\n"
        '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call>'
    )
    cleaned, calls = recover_tool_calls(content, _pat())
    assert cleaned == "Let me check that."
    assert len(calls) == 1
    assert calls[0]["type"] == "function"
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Paris"}
    assert calls[0]["id"].startswith("call_")


def test_recovers_multiple_tool_calls():
    content = (
        '<tool_call>{"name": "a", "arguments": {"x": 1}}</tool_call>'
        '<tool_call>{"name": "b", "arguments": {"y": 2}}</tool_call>'
    )
    cleaned, calls = recover_tool_calls(content, _pat())
    assert cleaned == ""
    assert [c["function"]["name"] for c in calls] == ["a", "b"]


def test_accepts_parameters_key_and_string_arguments():
    content = '<tool_call>{"name": "f", "parameters": {"a": 1}}</tool_call>'
    _, calls = recover_tool_calls(content, _pat())
    assert json.loads(calls[0]["function"]["arguments"]) == {"a": 1}

    content2 = '<tool_call>{"name": "f", "arguments": "{\\"a\\": 1}"}</tool_call>'
    _, calls2 = recover_tool_calls(content2, _pat())
    assert calls2[0]["function"]["arguments"] == '{"a": 1}'


def test_malformed_block_is_left_in_content():
    content = "before <tool_call>not json</tool_call> after"
    cleaned, calls = recover_tool_calls(content, _pat())
    assert calls == []
    assert cleaned == content


def test_no_tool_call_tag_is_noop():
    cleaned, calls = recover_tool_calls("just a normal answer", _pat())
    assert calls == []
    assert cleaned == "just a normal answer"


def test_adapt_response_moves_calls_and_sets_finish_reason():
    profile = QwenProfile(ProfileConfig())
    response = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '<tool_call>{"name": "search", "arguments": {"q": "x"}}</tool_call>',
                },
                "finish_reason": "stop",
            }
        ]
    }
    out = profile.adapt_response(response, had_tools=True)
    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] is None
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "search"


def test_adapt_response_respects_existing_structured_tool_calls():
    profile = QwenProfile(ProfileConfig())
    response = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_x", "type": "function",
                         "function": {"name": "n", "arguments": "{}"}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    out = profile.adapt_response(response, had_tools=True)
    # untouched
    assert out["choices"][0]["message"]["tool_calls"][0]["id"] == "call_x"


def test_adapt_response_skips_when_no_tools_in_request():
    profile = QwenProfile(ProfileConfig())
    response = {
        "choices": [
            {"index": 0, "message": {"role": "assistant",
                                     "content": "<tool_call>{}</tool_call>"},
             "finish_reason": "stop"}
        ]
    }
    # had_tools=False: leave the content alone (no tools were offered).
    out = profile.adapt_response(response, had_tools=False)
    assert out["choices"][0]["message"]["content"] == "<tool_call>{}</tool_call>"


def test_guided_json_translation_when_enabled():
    profile = QwenProfile(ProfileConfig(guided_json=True, guided_decoding_backend="xgrammar"))
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    payload = {
        "model": "x",
        "messages": [],
        "response_format": {"type": "json_schema", "json_schema": {"schema": schema}},
    }
    out = profile.prepare_request(payload, "Qwen-upstream")
    assert out["model"] == "Qwen-upstream"
    assert out["guided_json"] == schema
    assert out["guided_decoding_backend"] == "xgrammar"


def test_prepare_request_strips_reasoning_effort():
    profile = QwenProfile(ProfileConfig())
    out = profile.prepare_request({"model": "m", "messages": [], "reasoning_effort": "high"}, "up")
    assert "reasoning_effort" not in out
    assert out["model"] == "up"
