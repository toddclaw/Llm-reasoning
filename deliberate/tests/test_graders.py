from deliberate.eval.graders import grade
from deliberate.eval.runner import Completion
from deliberate.eval.task import GradeSpec, RequestSpec, Task


def _task(grade_spec: dict, tools=None) -> Task:
    req = {"messages": [{"role": "user", "content": "x"}]}
    if tools:
        req["tools"] = tools
    return Task(id="t", request=RequestSpec(**req), grade=GradeSpec(**grade_spec))


def _text(content) -> Completion:
    return Completion(message={"role": "assistant", "content": content}, finish_reason="stop")


def _calls(calls) -> Completion:
    return Completion(
        message={"role": "assistant", "content": None, "tool_calls": calls},
        finish_reason="tool_calls",
    )


def test_numeric_grader_tolerance_and_extraction():
    t = _task({"type": "numeric", "expected": 42})
    assert grade(t, _text("The answer is 42.")).passed
    assert not grade(t, _text("43")).passed
    assert grade(_task({"type": "numeric", "expected": 42, "tolerance": 1}), _text("43")).passed


def test_exact_and_contains_and_regex():
    assert grade(_task({"type": "exact", "expected": "Tokyo"}), _text(" tokyo ")).passed
    assert grade(_task({"type": "contains", "expected": "Tokyo"}),
                 _text("It is Tokyo, Japan.")).passed
    assert grade(_task({"type": "regex", "expected": r"tok\w+"}), _text("Tokyo")).passed


def test_any_grader_is_transparency_check():
    assert grade(_task({"type": "any"}), _text("hello")).passed
    assert not grade(_task({"type": "any"}), _text("   ")).passed


def _tc(name, args_json):
    return {"id": "call_1", "type": "function",
            "function": {"name": name, "arguments": args_json}}


def test_tool_call_grader_happy_path_sets_validity():
    t = _task({"type": "tool_call", "expected_name": "get_weather",
               "expected_args": {"city": "Paris"}},
              tools=[{"type": "function", "function": {"name": "get_weather"}}])
    res = grade(t, _calls([_tc("get_weather", '{"city": "Paris", "units": "c"}')]))
    assert res.passed and res.tool_call_valid is True


def test_tool_call_grader_wrong_name_fails_but_still_valid():
    t = _task({"type": "tool_call", "expected_name": "get_weather"},
              tools=[{"type": "function", "function": {"name": "get_weather"}}])
    res = grade(t, _calls([_tc("search", "{}")]))
    assert not res.passed and res.tool_call_valid is True


def test_tool_call_grader_prose_instead_of_call_is_invalid():
    # The Qwen failure mode: narrated call, no structured tool_calls.
    t = _task({"type": "tool_call", "expected_name": "get_weather"},
              tools=[{"type": "function", "function": {"name": "get_weather"}}])
    res = grade(t, _text('<tool_call>{"name":"get_weather"}</tool_call>'))
    assert not res.passed and res.tool_call_valid is False


def test_tool_call_grader_bad_json_args_is_invalid():
    t = _task({"type": "tool_call", "expected_name": "f"},
              tools=[{"type": "function", "function": {"name": "f"}}])
    res = grade(t, _calls([_tc("f", "{not json")]))
    assert not res.passed and res.tool_call_valid is False


def test_json_schema_grader():
    schema = {"type": "object", "properties": {"name": {"type": "string"},
                                               "age": {"type": "integer"}},
              "required": ["name", "age"]}
    t = _task({"type": "json_schema", "schema": schema})
    assert grade(t, _text('{"name": "Ada", "age": 36}')).passed
    assert not grade(t, _text('{"name": "Ada"}')).passed          # missing required
    assert not grade(t, _text("not json")).passed


def test_runner_error_fails_and_marks_tool_invalid_for_tool_task():
    t = _task({"type": "tool_call", "expected_name": "f"},
              tools=[{"type": "function", "function": {"name": "f"}}])
    res = grade(t, Completion.errored("boom", 0.0))
    assert not res.passed and res.tool_call_valid is False
