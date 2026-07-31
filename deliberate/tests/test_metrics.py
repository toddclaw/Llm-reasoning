import math

from deliberate.eval.metrics import (
    Row,
    brier_score,
    compute_lift,
    expected_calibration_error,
    summarize,
)


def _row(target, task, seed, passed, tool_valid=None, kind="qa", pt=10, ct=5):
    return Row(
        target=target, task_id=task, kind=kind, seed=seed, passed=passed,
        score=1.0 if passed else 0.0, tool_call_valid=tool_valid,
        latency_ms=100.0, prompt_tokens=pt, completion_tokens=ct,
    )


def test_summarize_pass_rate_and_band_across_seeds():
    rows = [
        _row("base", "a", 0, True), _row("base", "b", 0, False),   # seed0: 50%
        _row("base", "a", 1, True), _row("base", "b", 1, True),    # seed1: 100%
    ]
    s = summarize(rows)["base"]
    assert s.n_tasks == 2 and s.n_seeds == 2
    assert math.isclose(s.pass_rate, 0.75)
    assert s.band == (0.5, 1.0)
    assert math.isclose(s.band_halfwidth, 0.25)


def test_summarize_tool_validity_only_over_tool_rows():
    rows = [
        _row("x", "t1", 0, True, tool_valid=True, kind="tool"),
        _row("x", "t2", 0, False, tool_valid=False, kind="tool"),
        _row("x", "q1", 0, True, tool_valid=None, kind="qa"),
    ]
    s = summarize(rows)["x"]
    assert math.isclose(s.tool_call_validity, 0.5)  # 1 of 2 tool rows valid


def test_compute_lift_overall_and_band():
    rows = [
        # base: 50% both seeds -> band 0
        _row("base", "a", 0, True), _row("base", "b", 0, False),
        _row("base", "a", 1, True), _row("base", "b", 1, False),
        # layer: 100% both seeds -> band 0
        _row("layer", "a", 0, True), _row("layer", "b", 0, True),
        _row("layer", "a", 1, True), _row("layer", "b", 1, True),
    ]
    summaries = summarize(rows)
    lift = compute_lift(summaries, "layer", "base")
    assert math.isclose(lift.overall, 0.5)
    assert lift.combined_band_halfwidth == 0.0
    assert lift.clears_band  # 0.5 lift, 0 band


def test_lift_clears_band_when_stable():
    # base: stable 50% (a always passes, b always fails) -> band 0
    # layer: stable 100% -> band 0 ; lift 0.5 > 0 combined band -> clears
    rows = [
        _row("base", "a", 0, True), _row("base", "b", 0, False),
        _row("base", "a", 1, True), _row("base", "b", 1, False),
        _row("layer", "a", 0, True), _row("layer", "b", 0, True),
        _row("layer", "a", 1, True), _row("layer", "b", 1, True),
    ]
    lift = compute_lift(summarize(rows), "layer", "base")
    assert math.isclose(lift.overall, 0.5) and lift.clears_band


def test_lift_within_band_is_flagged_not_significant():
    # base: stable 50% (band 0). layer: 75% but noisy (seed0=100%, seed1=50%) -> band 0.25
    # lift 0.25 == combined band 0.25 -> does NOT clear (not significant)
    rows = [
        _row("base", "a", 0, True), _row("base", "b", 0, False),
        _row("base", "a", 1, True), _row("base", "b", 1, False),
        _row("layer", "a", 0, True), _row("layer", "b", 0, True),
        _row("layer", "a", 1, True), _row("layer", "b", 1, False),
    ]
    lift = compute_lift(summarize(rows), "layer", "base")
    assert math.isclose(lift.overall, 0.25) and not lift.clears_band


def test_brier_and_ece():
    # perfectly calibrated & correct
    assert math.isclose(brier_score([(1.0, True), (1.0, True)]), 0.0)
    # confident and wrong
    assert math.isclose(brier_score([(1.0, False)]), 1.0)
    # ECE zero when confidence matches accuracy per bin
    pairs = [(0.0, False), (1.0, True)]
    assert math.isclose(expected_calibration_error(pairs, bins=10), 0.0, abs_tol=1e-9)
    # overconfident: conf 1.0 but only half correct -> ECE 0.5
    pairs2 = [(1.0, True), (1.0, False)]
    assert math.isclose(expected_calibration_error(pairs2, bins=10), 0.5)
