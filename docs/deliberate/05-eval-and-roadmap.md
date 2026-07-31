# 05 — Proving the Lift, and the Roadmap

The layer is only worth sharing if it demonstrably improves answers. So the eval is
built early and answers one question bluntly: **does base+Deliberate beat base, by
how much, at what latency cost, and which stages earn their keep?**

## 1. What we measure

A run is `(pipeline_config × backend_profile × benchmark) → scored results`, exactly
the "scaffold is config" discipline from Nightshift.

Headline:
- **`lift`** — accuracy/quality of `base+layer` minus `base` alone, per benchmark.
  If lift isn't clearly positive and larger than its noise band, the layer (or that
  stage) isn't pulling its weight.

Diagnostics:
| Metric | Tells you |
| ------ | --------- |
| `lift_by_stage` (ablations) | which stages actually help — drop the ones that don't |
| `calibration` (ECE / Brier) | does stated confidence track real correctness (the `frame` stage's core promise) |
| `substitution_catch_rate` | on a planted-substitution set, how often `frame` flags the easier-question trap |
| `tool_call_validity` | fraction of Qwen tool calls that parse + execute (the Claude-Code-pain metric) |
| `format_adherence` | structured-output validity vs the base model |
| `latency` p50/p95, `model_calls/req`, `tokens/req` | the cost side of the trade |
| `overthink_regression` | do easy questions stay fast **and** correct (guard against `frame` bloating trivia) |
| `refusal/hallucination delta` | does the layer reduce confident fabrication |

## 2. Benchmarks

Mix public suites (for comparability + shareability) with your own tasks:

| Suite | Probes |
| ----- | ------ |
| General reasoning (GSM8K/MATH-style, logic puzzles) | plan-act-verify, best-of-N |
| Knowledge QA with retrieval | `frame` inquiry, retrieval verifier, calibration |
| **Planted-substitution set** (custom) | does `frame` catch "answered an easier question" |
| **Calibration set** (custom, hand-scored) | confidence honesty |
| Tool-use / agent tasks | Qwen adaptation, tool-call validity |
| Structured extraction | grammar-constrained output |
| Coding (small) | exec verifier, best-of-N (bridges to Nightshift) |

Two references on every chart: the **base model alone** (the floor the layer must
beat) and, where relevant, a **frontier model** run online-and-explicit (the ceiling,
so you know remaining headroom). Same idea as Nightshift's baselines.

Discipline carried over: seeded determinism, a held-out split never used for tuning,
variance measured across ≥3 seeds (a 3-point "win" inside a 6-point band is not a
win), response caching so a one-stage change re-runs cheaply.

## 3. Roadmap

Ordered by risk: prove the layer helps *before* building breadth.

### Phase 0 — Passthrough proxy
- OpenAI-compatible server, streaming, `effort: off` = pure passthrough.
- Qwen adapter v1: tool-format translation + grammar-constrained tool calls +
  structured output. **This alone should noticeably fix pi (or Claude Code) + Qwen.**
- Backend client + per-replica admission cap.
- **Exit:** a pi agent driving Qwen3.5 *through* Deliberate has measurably higher
  tool-call validity (and completes more agent tasks) than pointing pi straight at
  vLLM, with no other change. Ship-worthy on its own.

### Phase 1 — Eval harness
- Benchmark loader, graders, ablation runner, calibration + substitution sets,
  variance + caching, HTML report with the two reference lines.
- **Exit:** one command produces base-vs-layer lift with variance bars.

### Phase 2 — The reasoning stages
- `frame` (Inquiry & Debiasing), `reflect`, `best_of_n` + verifiers,
  `plan_act_verify`. Classifier + effort×difficulty routing table.
- **Exit:** positive, variance-clearing `lift` on ≥3 benchmarks; `frame` shows
  measurable calibration improvement and substitution-catch; `overthink_regression`
  clean (easy stays easy).

### Phase 3 — Tuning & ablation
- Sweep the routing table, per-stage thinking-mode, N width, context budgets, prompt
  shims. Drop stages that don't earn their latency. Publish "which stages help, and
  when" — the real deliverable, and what makes it credible to share.
- **Exit:** documented, reproducible per-stage value; default pipeline chosen by data.

### Phase 4 — Parallelism hardening
- Fair queueing, priority classes, backpressure, speculative-cancel; horizontal
  replicas; `trace_id` propagation. Integrate with **pi** primarily via `base_url`
  ([04](04-parallelism-and-pidev.md) §4), plus optional task/priority header
  propagation from pi-fleet if available; verify the single-turn boundary (§5) holds
  through pi's tool loop.
- **Exit:** a parallel pi fleet (pi-fleet / pi-orchestration across worktrees) sustains
  high rack utilisation through Deliberate without tail-latency collapse or
  cross-caller starvation, under a load test.

### Phase 5 — Packaging & sharing
- `pip install deliberate`, Docker image, `deliberate serve|bench|trace`, the stage
  plugin API + docs, `generic`/`openai` profiles so it's not Qwen-locked, quickstart,
  permissive license, example pipelines.
- **Exit:** someone else stands it up in front of *their* model from the README and
  reproduces a lift number on a public benchmark.

### Phase 6 — Nightshift integration
- Point Nightshift's agents at Deliberate; move generic reasoning down into the layer;
  keep domain gates + the scrum/investigate state machines in Nightshift.
- **Exit:** Nightshift runs on Deliberate with equal-or-better results and less
  bespoke reasoning code — the foundation choice paid off.

## 4. Sequencing note

Phase 0 is independently valuable and low-risk — it fixes your immediate Claude-Code
pain and is shippable before any of the fancy reasoning exists. Do it first, get the
value, then let the eval harness (Phase 1) gate everything after it so no stage ships
without evidence it helps. That ordering is the whole philosophy of the layer applied
to building the layer.
