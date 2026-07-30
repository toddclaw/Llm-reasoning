# 08 — Roadmap

Phases are ordered by **risk retirement**, not by feature appeal. The riskiest
assumptions are (a) that a Qwen3-class model can produce acceptable code under
tight gates at all, and (b) that we can measure whether the scaffold is improving.
Both are retired by Phase 2.

Estimates assume Claude Opus doing the implementation in Claude Code, with you
reviewing. They are calendar-ish, not person-hours.

---

## Phase 0 — Foundations and a walking skeleton
**Retires:** "can this run offline on this laptop at all?"

Deliverables:
- Repo scaffold, `uv` project, CI for Nightshift itself (linted, typed, tested —
  we hold ourselves to the standard we're enforcing).
- Model serving: llama.cpp + llama-swap, OpenAI-compatible client, **grammar
  generation from pydantic schemas**, deterministic sampling profile.
- Sandbox: target-env image build, `--network=none` exec, resource limits.
- Blackboard: SQLite schema, artifact/record models, attestation.
- Two runners: `test` (pytest) and `lint`.
- One agent (`tdd-dev:impl`), one state transition, one gate (`G-GREEN-1`).
- `nightshift run` on a trivial task end to end.

**Exit criteria:**
- A single Python story goes `CONTRACTED → GREEN` on a real local Qwen model,
  fully offline, with an attested `TestRunRecord`.
- Bootstrap verified in a `--network=none` container.
- Measured: tokens/sec, model load time, swap time on the actual laptop. These
  numbers set every budget in the system, so get them early.

---

## Phase 1 — The gate battery and the eval harness
**Retires:** "can we measure quality mechanically?" — the highest-leverage phase.

Deliverables:
- Full RED/GREEN gate families: red proof + classification, AST vacuity, criterion
  coverage, diff coverage, mutation (Python), symbol resolution via pyright,
  readability rules, comprehension probe.
- **Bad-test corpus**: a permanent regression suite of vacuous/gamed tests that the
  gate battery must catch. Grow it forever.
- Gate feedback (`remediation`) generation.
- Eval harness: task format, seed bundles, hidden oracles, scorer, results DB,
  response cache, seeded determinism, HTML report with variance bars.
- 15 Python tasks (10 dev, 5 holdout).
- Baselines measured: naive single-prompt, and current scaffold.

**Exit criteria:**
- The bad-test corpus is caught at 100%.
- `nightshift eval run --playbook default` completes the 15-task suite unattended
  and produces a comparison report.
- Two playbook variants can be compared with variance bars, and the response cache
  makes a prompt-only change re-run in <25% of the original time.

---

## Phase 2 — The core scrum loop (Python only)
**Retires:** "does multi-agent + contract-first actually beat single-agent?"

Deliverables:
- PO, Architect, TDD Dev (3 invocations), Reviewer agents with real context
  assemblers and negative-containment tests.
- Full state machine through `ACCEPTED`, ladder rungs 1–3 and 6, progress detectors.
- Git worktree pool, branch-per-story, commit trailers.
- DEMONSTRATED gate with asciinema capture; DOCUMENTED gate with executed
  README/`--help`.
- Morning report v1.

**Exit criteria:**
- ≥60% `accept_rate` on the Phase-1 Python dev suite, with `gate_gap` ≤ 10%.
- Beats the naive single-agent baseline by ≥25 points of accept_rate at comparable
  or better token cost — **if it doesn't, stop and diagnose before building more.**
  This is the go/no-go for the entire thesis.
- Median attempts-to-green ≤ 3.

---

## Phase 3 — Iteration to quality
**Retires:** "can we tune the scaffold systematically?"

No new capabilities — this phase is pure optimisation, and it's where the "keep
iterating until it performs well" requirement actually gets satisfied.

Deliverables:
- Sweeps: thinking-mode per role, quantisation level, best-of-N width, context
  budgets, decomposition granularity, ladder shapes, exemplar count.
- Failure taxonomy auto-classification.
- Prompt/exemplar refinement driven by the taxonomy, not by intuition.
- Grow the suite to 30 tasks; holdout evaluation at the phase gate.

**Exit criteria:**
- ≥80% accept_rate on dev suite, ≥70% on **holdout** (a large dev/holdout gap means
  you overfit — fix that before proceeding).
- `gate_gap` ≤ 5%.
- Hallucinated-claim rate ≤ 1% per role.
- Documented, reproducible answer to "which scaffold components earn their cost",
  from ablations. This document is the real output of the phase.

---

## Phase 4 — C++, Bash, DevOps, DevSecOps
**Retires:** "does this generalise beyond Python?"

Deliverables:
- C++ domain playbook: CMake, GoogleTest/Catch2, clangd, sanitizers, gcovr,
  clang-tidy, mutation.
- Bash domain playbook: bats, shellcheck, shfmt, preamble gate.
- DevOps agent: from-scratch build, runtime-image separation, offline CI,
  reproducibility check, executable runbook.
- DevSecOps agent: semgrep/bandit/gitleaks, threat-model note, suppression
  discipline.
- +16 tasks (C++ and Bash), holdout maintained.

**Exit criteria:**
- ≥70% accept_rate on the C++ dev suite (C++ will lag Python; that's expected).
- Zero accepted stories that fail the from-scratch build.
- Sanitizer gate catches the seeded memory-safety tasks 100%.

---

## Phase 5 — Reverse engineering and vulnerability research
**Retires:** "can the same discipline work on analysis-shaped, not build-shaped, work?"

Deliverables:
- Hardened sandbox: microVM path for sample execution, seccomp, scope enforcement.
- RE agent + tooling (Ghidra headless, rizin, capa, angr) and the
  script-plus-report artifact with re-execution gating.
- VR agent + fuzzing infrastructure, crash triage/dedup/minimisation,
  `VulnFinding` with mandatory PoC and fix verification.
- Symbol-dictionary working memory for RE stories.
- +12 tasks with ground truth (crackmes, planted bugs, Juliet subset).

**Exit criteria:**
- RE: recovers the target algorithm with a passing differential test on ≥60% of RE
  tasks.
- VR: finds ≥70% of planted bugs with a working PoC, at a false-positive rate ≤20%.
- Zero sandbox escapes in an adversarial review of the isolation setup.

---

## Phase 6 — Full autonomy and UX
**Retires:** "can I actually leave it alone for nine hours?"

Deliverables:
- Scrum Master + Manager agents, ladder rungs 4–5, parking with quality questions.
- Budgets, reserves, crash resume, sleep/wake survival, kill switch.
- Swap-aware, resource-class scheduler; background fuzz pool.
- UX agent, demo-cast review, error-message and help-text gates.
- Morning report v2 with embedded casts, trends, process health.

**Exit criteria:**
- Five consecutive unattended 8-hour runs on a real backlog with zero crashes, zero
  runaway stories, and zero accepted-but-broken stories.
- Every parked story's question is one you can answer in under a minute.
- You choose to run it again the next night without being asked. That's the real
  exit criterion.

---

## Phase 7 (optional) — Learning from trajectories
- Harvest verified trajectories, LoRA per role, evaluate on holdout, adopt only if
  it beats base on holdout.
- Role-specific adapters give genuinely different agents at negligible memory cost.

---

## Cross-cutting, from day one

- **Trajectory logging in training-ready JSONL** — free now, valuable in Phase 7.
- **Nightshift eats its own dog food** from Phase 2: point it at its own backlog for
  small, well-specified stories. Nothing surfaces harness weaknesses faster.
- **ADRs for the seven decisions** listed in [01](01-architecture.md) §9.
- **The bad-test corpus grows every time a vacuous test escapes.** Every `gate_gap`
  incident becomes a permanent regression test for the gate battery — that's the
  mechanism by which the system actually gets trustworthy over time.
