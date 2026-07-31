import asyncio
from pathlib import Path

from deliberate.eval import (
    Completion,
    ScriptedRunner,
    compute_lift,
    load_suite,
    render_html,
    render_text,
    run_suite,
    summarize,
)
from deliberate.eval.cache import ResponseCache
from deliberate.eval.runner import CachingRunner
from deliberate.eval.task import GradeSpec, RequestSpec, Task


def _num_task(tid, q, expected):
    return Task(id=tid, kind="qa", request=RequestSpec(messages=[{"role": "user", "content": q}]),
                grade=GradeSpec(type="numeric", expected=expected))


def _tool_task(tid, q, name):
    return Task(
        id=tid, kind="tool",
        request=RequestSpec(
            messages=[{"role": "user", "content": q}],
            tools=[{"type": "function", "function": {"name": name}}],
        ),
        grade=GradeSpec(type="tool_call", expected_name=name),
    )


def _prose(content):
    return Completion(message={"role": "assistant", "content": content}, finish_reason="stop")


def _call(name):
    return Completion(
        message={"role": "assistant", "content": None,
                 "tool_calls": [{"id": "c1", "type": "function",
                                 "function": {"name": name, "arguments": "{}"}}]},
        finish_reason="tool_calls",
    )


def test_harness_computes_lift_from_tool_recovery():
    tasks = [_num_task("m", "17+25?", 42), _tool_task("w", "weather?", "get_weather")]

    base = ScriptedRunner("base", {
        "17+25?": _prose("42"),
        "weather?": _prose('<tool_call>{"name":"get_weather"}</tool_call>'),  # narrated, unparsed
    })
    layer = ScriptedRunner("layer", {
        "17+25?": _prose("42"),
        "weather?": _call("get_weather"),  # structured (as the adapter would produce)
    })

    rows = asyncio.run(run_suite([base, layer], tasks, seeds=[0, 1]))
    summaries = summarize(rows)

    assert summaries["base"].per_kind["qa"] == 1.0
    assert summaries["base"].per_kind["tool"] == 0.0
    assert summaries["layer"].per_kind["tool"] == 1.0
    assert summaries["base"].tool_call_validity == 0.0
    assert summaries["layer"].tool_call_validity == 1.0

    lift = compute_lift(summaries, "layer", "base")
    assert lift.overall == 0.5          # layer passes both tasks, base only the qa one
    assert lift.per_kind["tool"] == 1.0
    assert lift.clears_band

    # reports render
    assert "LIFT" in render_text(summaries, lift)
    html = render_html(rows, summaries, lift, {"suite": "test"})
    assert "<!doctype html>" in html and "get_weather" not in html  # task ids shown, not internals
    assert "w" in html and "m" in html


class _CountingRunner:
    name = "count"
    model = "scripted"

    def __init__(self):
        self.calls = 0

    async def run(self, request, seed):
        self.calls += 1
        return _prose("42")


def test_caching_runner_skips_repeat_calls(tmp_path):
    inner = _CountingRunner()
    cache = ResponseCache(tmp_path)
    cached = CachingRunner(inner, cache)
    task = _num_task("m", "17+25?", 42)

    asyncio.run(run_suite([cached], [task], seeds=[0]))
    asyncio.run(run_suite([cached], [task], seeds=[0]))  # same key -> served from disk
    assert inner.calls == 1

    asyncio.run(run_suite([cached], [task], seeds=[1]))  # different seed -> new call
    assert inner.calls == 2


def test_load_starter_suite():
    suite_dir = Path(__file__).resolve().parent.parent / "bench" / "tasks"
    tasks = load_suite(suite_dir)
    by_id = {t.id: t for t in tasks}
    assert {"qa_arithmetic", "tool_weather", "structured_person", "transparency_hello"} <= set(by_id)
    assert by_id["tool_weather"].has_tools
    assert by_id["qa_arithmetic"].grade.type == "numeric"


def test_load_code_suite():
    suite_dir = Path(__file__).resolve().parent.parent / "bench" / "tasks_code"
    tasks = load_suite(suite_dir)
    by_id = {t.id: t for t in tasks}
    assert {"code_fib", "code_fizzbuzz", "code_anagram", "code_roman"} <= set(by_id)
    assert by_id["code_fib"].grade.type == "exec"
    assert by_id["code_fib"].grade.tests is not None
