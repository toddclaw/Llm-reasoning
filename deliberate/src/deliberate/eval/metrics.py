"""Aggregation: pass-rate, lift, variance bands, tool-call validity, calibration.

The headline number is **lift** — the layer's pass-rate minus the base's — reported
with a **variance band** so a small "improvement" inside the noise is not mistaken
for a real one (docs/deliberate/05-eval-and-roadmap.md §1). Calibration (ECE/Brier)
is plumbed here and activates in Phase 2 when the ``frame`` stage emits a confidence.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Row:
    target: str
    task_id: str
    kind: str
    seed: int
    passed: bool
    score: float
    tool_call_valid: bool | None
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None = None
    confidence: float | None = None  # populated in Phase 2 (frame stage)
    error: str | None = None


@dataclass
class TargetSummary:
    name: str
    n_tasks: int
    n_seeds: int
    pass_rate: float
    seed_pass_rates: list[float]
    tool_call_validity: float | None
    mean_latency_ms: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float | None
    per_kind: dict[str, float] = field(default_factory=dict)
    # calibration (populated when frame emitted confidences)
    ece: float | None = None
    brier: float | None = None
    n_confident: int = 0

    @property
    def band(self) -> tuple[float, float]:
        if not self.seed_pass_rates:
            return (self.pass_rate, self.pass_rate)
        return (min(self.seed_pass_rates), max(self.seed_pass_rates))

    @property
    def band_halfwidth(self) -> float:
        lo, hi = self.band
        return (hi - lo) / 2.0


@dataclass
class Lift:
    layer: str
    base: str
    overall: float
    per_kind: dict[str, float]
    combined_band_halfwidth: float

    @property
    def clears_band(self) -> bool:
        """True when the lift is larger than the two targets' combined noise."""
        return abs(self.overall) > self.combined_band_halfwidth


@dataclass
class VariantVerdict:
    name: str
    pass_rate: float
    band: tuple[float, float]
    lift: float  # vs baseline
    clears_band: bool
    per_kind_lift: dict[str, float]
    mean_latency_ms: float
    total_cost_usd: float | None
    ece: float | None


@dataclass
class SweepAnalysis:
    baseline: str
    variants: list[VariantVerdict]  # ranked by pass_rate desc
    suggested: str | None  # best variant that clears the band, else the baseline


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else 0.0


def summarize(rows: list[Row]) -> dict[str, TargetSummary]:
    by_target: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_target[r.target].append(r)

    summaries: dict[str, TargetSummary] = {}
    for target, trows in by_target.items():
        task_ids = sorted({r.task_id for r in trows})
        seeds = sorted({r.seed for r in trows})

        # per-seed suite pass-rate = mean over tasks (equal weight per task)
        seed_rates: list[float] = []
        for s in seeds:
            per_seed = [r for r in trows if r.seed == s]
            seed_rates.append(_mean([1.0 if r.passed else 0.0 for r in per_seed]))

        tool_rows = [r for r in trows if r.tool_call_valid is not None]
        tool_validity = (
            _mean([1.0 if r.tool_call_valid else 0.0 for r in tool_rows]) if tool_rows else None
        )

        per_kind: dict[str, float] = {}
        for kind in sorted({r.kind for r in trows}):
            krows = [r for r in trows if r.kind == kind]
            per_kind[kind] = _mean([1.0 if r.passed else 0.0 for r in krows])

        costs = [r.cost_usd for r in trows if r.cost_usd is not None]
        pairs = calibration_pairs(trows)
        summaries[target] = TargetSummary(
            name=target,
            n_tasks=len(task_ids),
            n_seeds=len(seeds),
            pass_rate=_mean(seed_rates),
            seed_pass_rates=seed_rates,
            tool_call_validity=tool_validity,
            mean_latency_ms=_mean([r.latency_ms for r in trows]),
            total_prompt_tokens=sum(r.prompt_tokens for r in trows),
            total_completion_tokens=sum(r.completion_tokens for r in trows),
            total_cost_usd=(sum(costs) if costs else None),
            per_kind=per_kind,
            ece=(expected_calibration_error(pairs) if pairs else None),
            brier=(brier_score(pairs) if pairs else None),
            n_confident=len(pairs),
        )
    return summaries


def analyze_sweep(summaries: dict[str, TargetSummary], baseline: str) -> SweepAnalysis:
    """Rank every non-baseline variant by pass-rate and lift over the baseline.

    ``suggested`` is the highest-pass-rate variant whose lift clears the combined
    noise band (positive and significant); ties broken by lower cost then latency.
    If nothing clears the band, the baseline is suggested — the honest "no stage
    earned promotion" outcome the gating policy calls for.
    """
    verdicts: list[VariantVerdict] = []
    for name, s in summaries.items():
        if name == baseline:
            continue
        lift = compute_lift(summaries, name, baseline)
        verdicts.append(
            VariantVerdict(
                name=name,
                pass_rate=s.pass_rate,
                band=s.band,
                lift=lift.overall,
                clears_band=(lift.overall > 0 and lift.clears_band),
                per_kind_lift=lift.per_kind,
                mean_latency_ms=s.mean_latency_ms,
                total_cost_usd=s.total_cost_usd,
                ece=s.ece,
            )
        )
    verdicts.sort(key=lambda v: v.pass_rate, reverse=True)

    clearing = [v for v in verdicts if v.clears_band]
    if clearing:
        best = max(
            clearing,
            key=lambda v: (v.pass_rate, -(v.total_cost_usd or 0.0), -v.mean_latency_ms),
        )
        suggested = best.name
    else:
        suggested = baseline
    return SweepAnalysis(baseline=baseline, variants=verdicts, suggested=suggested)


def compute_lift(summaries: dict[str, TargetSummary], layer: str, base: str) -> Lift:
    a, b = summaries[layer], summaries[base]
    kinds = set(a.per_kind) | set(b.per_kind)
    per_kind = {k: a.per_kind.get(k, 0.0) - b.per_kind.get(k, 0.0) for k in sorted(kinds)}
    return Lift(
        layer=layer,
        base=base,
        overall=a.pass_rate - b.pass_rate,
        per_kind=per_kind,
        combined_band_halfwidth=a.band_halfwidth + b.band_halfwidth,
    )


# -- calibration (activates in Phase 2 when confidences exist) -------------

def brier_score(pairs: list[tuple[float, bool]]) -> float:
    """Mean squared error between predicted confidence and outcome. Lower is better."""
    if not pairs:
        return 0.0
    return _mean([(conf - (1.0 if correct else 0.0)) ** 2 for conf, correct in pairs])


def expected_calibration_error(pairs: list[tuple[float, bool]], bins: int = 10) -> float:
    """ECE: average gap between confidence and accuracy across confidence bins."""
    if not pairs:
        return 0.0
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for conf, correct in pairs:
        idx = min(bins - 1, max(0, int(conf * bins)))
        buckets[idx].append((conf, correct))
    n = len(pairs)
    ece = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        acc = _mean([1.0 if correct else 0.0 for _, correct in bucket])
        conf = _mean([c for c, _ in bucket])
        ece += (len(bucket) / n) * abs(acc - conf)
    return ece


def calibration_pairs(rows: list[Row]) -> list[tuple[float, bool]]:
    return [(r.confidence, r.passed) for r in rows if r.confidence is not None]


def cost_of(usage_prompt: int, usage_completion: int, price: dict[str, float] | None) -> float | None:
    if not price:
        return None
    return (
        usage_prompt / 1_000_000 * price.get("input_per_m", 0.0)
        + usage_completion / 1_000_000 * price.get("output_per_m", 0.0)
    )
