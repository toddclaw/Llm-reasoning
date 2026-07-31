# 08 — Roadmap

Phases are ordered by **risk retirement**, not by feature appeal. The riskiest
assumptions are (a) that the scaffold + local models can produce **trustworthy**
code under strict gates — good enough to accept unseen in the morning — and (b) that
we can measure whether the scaffold is improving. Both are retired by Phase 2.

Ordering reflects the answers in [09](09-open-questions.md):
**Python forward development is the first vertical slice** (A3); **almost all work is
on existing repos**, so the Codebase Cartographer lands in Phase 2 (A5); the first
real milestone is **one trustworthy medium feature**, epics and multi-day backlogs
come only after that trust exists (A7); and the **INVESTIGATE path plus C/C++
analysis tooling land together** once BUILD is proven (A6), earlier than the original
Phase-5 ordering. There is **no quantisation sweep** — the checkpoints are FP8 and
run natively on the H200s (A1).

Gates start **strict** (A9): mutation ≥75%, diff branch coverage ≥90%, zero `major`
review findings, zero unjustified suppressions — from Phase 1, not relaxed in later
phases.

Estimates assume Claude Opus doing the implementation in Claude Code, with you
reviewing. They are calendar-ish, not person-hours.

---

## Phase 0 — Foundations, topology, and a walking skeleton
**Retires:** "does the three-tier topology work end to end, offline?"

Deliverables:
- Repo scaffold, `uv` project, CI for Nightshift itself (linted, typed, tested —
  we hold ourselves to the standard we're enforcing).
- **Topology bring-up** ([05](05-inference-and-topology.md) §1): vLLM on the rack
  serving both FP8 checkpoints resident; agent container with the egress allowlist
  (rack + tunnels only) and a test asserting nothing else is reachable; the
  host-owned remote-runner broker with stable tunnels (A18) to a Proxmox **build VM**
  (gate runners live here, A17) and a Proxmox **target VM**.
- Model layer: OpenAI-compatible client to vLLM, **grammar generation from pydantic
  schemas** via `guided_json`, deterministic sampling profile, prefix-cache-friendly
  prompt layout with a stability regression test.
- Provenance: attestation key held on the host; the remote-runner broker executes on
  the build VM / target VM over the stable tunnels and attests results **on the host**
  (evidence flows by pull, never push); every Record captures the VM identity + state
  fingerprint (A18).
- Blackboard: SQLite schema, artifact/record models, attestation verification.
- Two runners: `test` (pytest) and `lint`.
- One agent (`tdd-dev:impl`), one state transition, one gate (`G-GREEN-1`).
- `nightshift run --path build` on a trivial task end to end.

**Exit criteria:**
- A single Python story goes `CONTRACTED → GREEN` against the rack models, fully
  offline, with a `TestRunRecord` attested on the host.
- The agent container provably cannot reach the internet, the host filesystem, git
  push, or ssh — asserted by tests.
- Neither the build VM nor a target VM can initiate a connection back to the laptop,
  and the build VM cannot reach the target VM — asserted by tests.
- Measured: rack tokens/sec under concurrency, and **build-VM gate-runner throughput**
  (compile, test, mutation wall-clock). These set every budget, so get them early —
  the build VM is the bottleneck now, not inference.

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

## Phase 2 — The core scrum loop on existing Python repos
**Retires:** "does multi-agent + contract-first beat single-agent, and does one
medium feature come out trustworthy?"

Deliverables:
- **Codebase Cartographer** + `MAPPED` state + `CodebaseMap` (A5 — almost all work
  is on existing repos): convention inference, exemplar extraction, `danger_zones`,
  characterization-test sub-step. Map digest wired into the stable prompt prefix.
- PO, Architect, TDD Dev (3 invocations), Reviewer agents with real context
  assemblers and negative-containment tests.
- Full BUILD state machine through `ACCEPTED`, ladder rungs 1–3 and 6, progress
  detectors, best-of-N with the static pre-filter funnel
  ([05](05-inference-and-topology.md) §4).
- Architect self-consistency (k-sample consensus, disagreement surfaced).
- Git worktree pool, branch-per-story, commit trailers, blast-radius write-scope.
- DEMONSTRATED gate with asciinema capture **run in a Proxmox target VM over the
  tunnel**; DOCUMENTED gate with executed README/`--help`.
- Morning report v1 with the parked-questions section and an "answer the parked
  questions" CLI (A10 — the morning review-and-answer loop is the operating model).

**Exit criteria:**
- **The headline milestone (A7): one medium feature on a real existing Python repo
  comes out `ACCEPTED` and is genuinely finished** — you inspect it and would ship
  it. Repeat on 3 different features before trusting the loop.
- ≥60% `accept_rate` on the Phase-1 Python dev suite, with `gate_gap` ≤ 10%.
- Beats the naive single-agent baseline by ≥25 points of accept_rate — **if it
  doesn't, stop and diagnose before building more.** Go/no-go for the whole thesis.
- Median attempts-to-green ≤ 3.

---

## Phase 3 — Iteration to quality
**Retires:** "can we tune the scaffold systematically?"

No new capabilities — this phase is pure optimisation, and it's where the "keep
iterating until it performs well" requirement actually gets satisfied.

Deliverables:
- Sweeps: thinking-mode per role, **per-role context budget {8k,24k,64k}**
  ([05](05-inference-and-topology.md) §6), best-of-N width, decomposition
  granularity, ladder shapes, exemplar count. (No quant sweep — FP8 is fixed.)
- Optional ablation: run the suite with a *small* Qwen behind each class to measure
  scaffold-vs-weights value — the preserved form of the original thesis.
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

## Phase 4 — C/C++ analysis tooling + the INVESTIGATE path
**Retires:** "can the same discipline answer *questions about a system*, not just
build software?" — and it needs C/C++ tooling to do so (A6: RE targets are C/C++).

Grouped this way because both of your near-term needs land here together: the
INVESTIGATE path and the C/C++ analysis toolchain it depends on. Forward C/C++
*development* follows in Phase 5; INVESTIGATE comes first because it's the earlier
of your two real workloads to need C/C++.

Deliverables:
- **INVESTIGATE state machine** (`POSED→…→ANSWERED`) and roster (Analyst, Verifier,
  Reporter, Manager) over the shared runtime — [10](10-dual-path-and-existing-repos.md).
- `--path investigate` selection; `scope.yaml` enforcement by **local-only CIDR**
  (A19) in the broker; `Question`/`Evidence`/`Finding`/`Verification`/`AnalysisReport`
  artifacts.
- **Cross-path auto-seeding** (A20): a verified `Finding` auto-creates a
  provenance-linked BUILD story (at `INTAKE`, PoC attached as the RED seed), flagged
  in the morning report for your veto — [10](10-dual-path-and-existing-repos.md) §1a.
- C/C++ analysis toolchain in the agent image and target VM templates: Ghidra
  headless, rizin/r2pipe, capa, angr, gdb/pwndbg, objdump/readelf.
- **Script-produces-evidence discipline**: Analyst emits scripts, harness runs them
  in a target VM over the tunnel, output is attested Evidence; Verifier reproduces
  independently. This is the A6 requirement — every conclusion backed by
  reproducible data — made mechanical.
- Symbol-dictionary working memory (blackboard-backed) for multi-step analysis.
- Sample-detonation path: run untrusted binaries only in a Proxmox VM with no route
  back to the laptop; the topology, not seccomp, is the isolation.
- +12 INVESTIGATE tasks with ground truth (crackmes, planted bugs, Juliet subset,
  algorithm-recovery scored by differential testing).

**Exit criteria:**
- Every `Finding` in a passing run is reproduced by the Verifier from attested data;
  zero unbacked claims survive to the report (the INVESTIGATE F1–F4 gates hold).
- RE: recovers the target algorithm with a passing differential test on ≥60% of RE
  tasks.
- VR: finds ≥70% of planted bugs with a working PoC, false-positive rate ≤20%.
- A verified finding auto-seeds a BUILD story that appears in the morning report with
  its evidence attached and is vetoable before the next run.
- Confirmed under adversarial review: a target VM cannot initiate a connection to the
  laptop, and scope enforcement rejects any out-of-CIDR / non-local destination.

---

## Phase 5 — C/C++ forward development, Bash, DevOps, DevSecOps
**Retires:** "does the BUILD path generalise from Python to C/C++?"

Deliverables:
- C++ domain playbook: CMake, GoogleTest/Catch2, clangd, sanitizers, gcovr,
  clang-tidy, mutation ([06](06-domain-playbooks.md) §2). Much of the C/C++ analysis
  toolchain from Phase 4 is reused here.
- Bash domain playbook: bats, shellcheck, shfmt, preamble gate.
- DevOps agent: from-scratch build, runtime-image separation, offline CI in the
  Proxmox target, reproducibility check, executable runbook.
- DevSecOps agent: semgrep/bandit/gitleaks, threat-model note, suppression
  discipline.
- +16 BUILD tasks (C++ and Bash), holdout maintained.

**Exit criteria:**
- ≥70% accept_rate on the C++ dev suite (C++ will lag Python; that's expected).
- Zero accepted stories that fail the from-scratch build.
- Sanitizer gate catches the seeded memory-safety tasks 100%.

---

## Phase 6 — Full autonomy and UX
**Retires:** "can I actually leave it alone for nine hours?"

Deliverables:
- Scrum Master + Manager agents, ladder rungs 4–5, parking with quality questions.
- Epic decomposition + multi-day backlog scheduling (A7 — only now, after single
  medium features are trustworthy; a backlog spanning 2–10 days becomes viable).
- Budgets, reserves, crash resume, sleep/wake survival, kill switch.
- Resource-class scheduler tuned for the inference-abundant / gate-bound regime
  ([07](07-overnight-autonomy.md) §5); background fuzz pool.
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
