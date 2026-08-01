from deliberate.config import BackendConfig
from deliberate.eval.metrics import Row, analyze_sweep, summarize
from deliberate.eval.report import render_sweep_html, render_sweep_text
from deliberate.eval.sweep import GridSpec, SweepSpec, build_sweep_runners
from deliberate.eval.cache import ResponseCache


def _spec(**kw):
    base = dict(suite="bench/tasks", backend=BackendConfig(endpoint="x", model="m"))
    base.update(kw)
    return SweepSpec(**base)


def test_expand_ablation_buildup_and_leave_one_out():
    names = {v.name: v.stages for v in _spec(ablation=["frame", "best_of_n", "reflect"]).expand()}
    assert names["buildup:passthrough"] == []
    assert names["buildup:frame"] == ["frame"]
    assert names["buildup:frame+best_of_n+reflect"] == ["frame", "best_of_n", "reflect"]
    assert names["no_frame"] == ["best_of_n", "reflect"]
    # no_reflect == buildup:frame+best_of_n, so it is deduped away
    assert "no_reflect" not in names


def test_expand_grid():
    spec = _spec(grid=GridSpec(stage="best_of_n", param="n", values=[1, 3, 5],
                               base_stages=["best_of_n", "reflect"]))
    variants = {v.name: v for v in spec.expand()}
    assert variants["best_of_n.n=3"].stage_params == {"best_of_n": {"n": 3}}
    assert variants["best_of_n.n=5"].stages == ["best_of_n", "reflect"]


def test_expand_dedupes_and_drops_baseline_equivalent():
    # a variant equal to the baseline (direct, no stages) is dropped
    spec = _spec(baseline_mode="direct", baseline_stages=[],
                 variants=[{"name": "dup", "mode": "direct", "stages": []},
                           {"name": "real", "stages": ["frame"]}])
    names = [v.name for v in spec.expand()]
    assert "dup" not in names and "real" in names


def _rows(target, per_seed_pass, kind="qa", conf=None):
    """per_seed_pass: list of pass-fractions to realize with 2 tasks per seed."""
    rows = []
    for seed, frac in enumerate(per_seed_pass):
        # realize frac with two tasks: (True,True)=1.0, (True,False)=0.5, (False,False)=0.0
        passes = {1.0: [True, True], 0.5: [True, False], 0.0: [False, False]}[frac]
        for i, p in enumerate(passes):
            rows.append(Row(target=target, task_id=f"t{i}", kind=kind, seed=seed,
                            passed=p, score=float(p), tool_call_valid=None,
                            latency_ms=100, prompt_tokens=10, completion_tokens=5,
                            confidence=conf))
    return rows


def test_analyze_sweep_picks_best_clearing_variant():
    rows = (_rows("base", [0.5, 0.5])          # stable 50%
            + _rows("A", [1.0, 1.0])           # stable 100% -> lift 0.5, clears
            + _rows("B", [0.5, 1.0]))          # noisy 75%, band 0.25 -> lift 0.25 == band, no clear
    summaries = summarize(rows)
    analysis = analyze_sweep(summaries, "base")
    assert [v.name for v in analysis.variants][0] == "A"  # ranked by pass_rate
    assert analysis.suggested == "A"
    a = next(v for v in analysis.variants if v.name == "A")
    assert a.clears_band and abs(a.lift - 0.5) < 1e-9


def test_analyze_sweep_suggests_baseline_when_nothing_clears():
    rows = _rows("base", [0.5, 0.5]) + _rows("A", [0.5, 1.0])  # A noisy, lift within band
    analysis = analyze_sweep(summarize(rows), "base")
    assert analysis.suggested == "base"


def test_calibration_populated_from_confidences():
    # confidence matches correctness -> near-zero ECE
    rows = (_rows("cal", [1.0, 1.0], conf=0.95)      # correct + high conf
            + _rows("cal", [0.0, 0.0], conf=0.05, kind="qa2"))  # wrong + low conf
    s = summarize(rows)["cal"]
    assert s.n_confident == 8
    assert s.ece is not None and s.ece < 0.15
    assert s.brier is not None


def test_sweep_report_renders():
    rows = _rows("base", [0.5, 0.5]) + _rows("A", [1.0, 1.0])
    summaries = summarize(rows)
    analysis = analyze_sweep(summaries, "base")
    text = render_sweep_text(summaries, analysis)
    assert "SUGGESTED DEFAULT: A" in text
    html = render_sweep_html(rows, summaries, analysis, {"model": "m"})
    assert "<!doctype html>" in html and "Suggested default" in html and "A" in html


def test_build_sweep_runners_count(tmp_path):
    spec = _spec(ablation=["frame", "reflect"])
    runners = build_sweep_runners(spec, ResponseCache(tmp_path))
    names = [r.name for r in runners]
    assert names[0] == "base"
    assert "buildup:frame" in names and "buildup:frame+reflect" in names
