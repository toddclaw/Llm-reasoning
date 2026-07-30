# 04 — Eval Harness and the Iteration Loop

Your requirement: *"test the reasoning structure against a real Qwen model on a set
of tasks and keep iterating until it performs really well."* That makes the
**scaffold the system under test**, and it needs the same rigour we're demanding of
the agents' output.

## 1. What is being evaluated

A run is a triple:

```
(playbook_version, model_set, task_suite) → Results
```

- **playbook** — every knob of the reasoning structure: prompts, context assembly
  budgets, gate thresholds, ladder shape, best-of-N width, decomposition limits,
  sampling params, tool allowlists.
- **model_set** — which weights back each model class.
- **task_suite** — versioned set of tasks with hidden oracles.

Because the scaffold is config, comparing two reasoning structures is a diff of two
YAML files and two result rows. That property is the whole point of P7.

## 2. Task format

```
tasks/<task_id>/
  task.yaml          # metadata, prompt, target env, difficulty, domain tags
  seed.bundle        # git bundle of the starting repo state
  README.md          # human description of what's being tested
tasks_oracles/<task_id>/
  oracle_tests/      # hidden tests, mounted ONLY into the scorer container
  checks.py          # custom programmatic checks
  rubric.yaml        # for judged dimensions
  reference/         # a known-good solution, for calibration only
```

```yaml
# task.yaml
id: py-cli-retry-backoff
domain: python
kind: feature                 # feature | bugfix | refactor | re | vuln | ops
difficulty: 2                 # 1-5
prompt: |
  Add exponential backoff with jitter to the HTTP client's retry logic.
  Configurable base delay and max attempts. Must not retry on 4xx except 429.
target_env: te-linux-x86_64-glibc2.36
budget: { wall_minutes: 45, tokens: 400000 }
tags: [error-handling, concurrency, cli]
holdout: false                # true ⇒ never used for tuning
```

**The oracle is invisible to every agent.** Enforced structurally: `tasks_oracles/`
is never bind-mounted into an agent sandbox, and the scorer runs in a separate
container after the run is sealed. If an agent could see the oracle, the eval
measures nothing.

## 3. Task suite composition

Target ~60 tasks at maturity, built up over the phases. Distribution:

| Domain | Count | Examples |
| ------ | ----- | -------- |
| Python feature | 12 | CLI flags, retry logic, parsers, async pipelines |
| Python bugfix | 8 | Failing test provided, root cause non-obvious |
| C++ feature | 10 | RAII wrapper, template utility, CMake target, ABI-stable API |
| C++ bugfix | 6 | UB, off-by-one, lifetime bug, data race (TSAN-detectable) |
| Bash/ops | 6 | Robust script with `set -euo pipefail`, signal handling, CI job |
| Refactor | 6 | Extract interface, break a cycle, kill duplication — behaviour must not change |
| Reverse engineering | 6 | Recover an algorithm from a stripped binary; crackme with known key |
| Vulnerability research | 6 | Planted CVE-class bug in a known codebase; Juliet/SARD subsets |

Every task's oracle must be **fully deterministic**. If you can't score it without a
model, it's not a task — it's a demo. (Judged dimensions like readability are
scored with a model but against a fixed rubric with a calibration set; see §5.)

**Holdout discipline:** 30% of tasks are `holdout: true` and are run only at phase
gates, never during tuning. Without this you will overfit prompts to twelve tasks
and be baffled when real work fails. Treat a holdout regression as a stop-the-line
event.

**Task authoring rule:** each task must be solvable by the reference solution within
the declared budget, verified once at authoring time. A task nothing can pass tells
you nothing.

## 4. Metrics

Primary (the headline number):

- **`accept_rate`** — fraction of tasks reaching `ACCEPTED` *and* passing the hidden
  oracle. Both conditions: passing our own gates but failing the oracle means the
  gates are too weak, and that gap is itself a metric (`gate_gap`).

Diagnostics — these are what you actually iterate on:

| Metric | Tells you |
| ------ | --------- |
| `gate_gap` | Accepted-but-oracle-failed rate. The single most important quality signal for the gate battery |
| `first_pass_rate[gate_id]` | Which gate is the bottleneck |
| `attempts_to_green` (median, p90) | Ladder efficiency |
| `ladder_rung_distribution` | How often we escalate/decompose/park |
| `hallucinated_claim_rate[role]` | Whether a prompt change made a role start fabricating |
| `mutation_score`, `diff_coverage` | Test quality, independent of pass/fail |
| `comprehension_score` | Test readability (G-RED-5) |
| `regression_rate` | Did it break pre-existing tests |
| `tokens_per_task`, `wall_per_task`, `swaps_per_task` | Cost — the overnight budget constraint |
| `park_rate` and `park_quality` | How often it gives up, and whether the parked question was actually answerable |
| `human_agreement` | On a 20-task calibration set, do the model-judged dimensions correlate with your own scores |

Track a **frontier ceiling**: periodically run the same suite with the Anthropic
provider enabled (explicitly, online, not during normal operation). The gap between
local and frontier under an identical scaffold tells you whether to invest in the
scaffold or accept the model's limit.

Also track a **naive baseline**: single-agent, no gates, "write the code" prompt on
the same model. If the full scaffold isn't beating that by a wide margin, something
is wrong — and early on, it might not be, which is exactly why you want the number.

## 5. Judged dimensions and calibration

Some things (readability, doc quality, error-message helpfulness) need a model
judge. Make it trustworthy:

1. Fixed rubric with anchored examples per score level, stored in the task suite.
2. Judge runs at temp 0 with a grammar-constrained scorecard output.
3. **Calibration set**: 20 samples you score by hand. Report judge/human agreement
   (Spearman + exact-match rate). If agreement drops below threshold after a rubric
   change, the rubric change is rejected.
4. Judge model is pinned separately from the working models, so improving the
   working model doesn't silently move the yardstick.

## 6. The iteration loop

```
                ┌──────────────────────────────┐
                │ 1. Hypothesis                │
                │   "reviewer findings without  │
                │    file:line cause churn"     │
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │ 2. Playbook variant           │
                │   playbooks/exp/NNN.yaml      │
                │   (diff from default)         │
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │ 3. Smoke suite (10 tasks)     │  ~1-2h
                │   fail fast, seeded, cached   │
                └──────────────┬───────────────┘
                     no ↙      ▼ promising
                ┌──────────────────────────────┐
                │ 4. Full dev suite (~40 tasks) │  overnight
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │ 5. Failure taxonomy           │
                │   auto-cluster trajectories   │
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │ 6. Promote or revert          │
                │   holdout check at phase gates│
                └──────────────────────────────┘
```

Practical requirements that make this loop survivable on a laptop:

- **Seeded determinism.** Fixed sampling seed per (task, role, attempt). Two runs of
  the same playbook must produce the same trajectory, otherwise you're measuring
  noise. Note llama.cpp is only bitwise-deterministic with fixed batch/threading
  config — pin those in the eval profile.
- **Variance measurement.** Determinism doesn't mean one seed is enough. Run the
  smoke suite at 3 seeds and report mean ± range; a 5-point "improvement" inside a
  12-point spread is not an improvement. This is the most common way to fool
  yourself here.
- **Response caching.** Content-addressed by `(model, prompt_sha, sampling)`. When
  you change only the reviewer prompt, everything upstream replays from cache. This
  turns a 10-hour suite into a 40-minute one and is worth building early.
- **Trajectory logs as JSONL** — every prompt, response, gate result, record. These
  are both the debugging surface and (later) fine-tuning data.
- **Replay CLI**: `nightshift eval replay <run_id> --story S-3 --from RED` to
  re-enter a failed trajectory at a specific point with a modified prompt. You will
  live in this command.

## 7. Failure taxonomy

Auto-classify every failed task from its trajectory (rules first, model only for the
residual), into a fixed set:

```
SPEC_MISREAD          - agent solved a different problem
CONTRACT_VIOLATION    - implementation diverged from architect's contract
API_HALLUCINATION     - referenced a symbol that doesn't exist  (→ G-GREEN-5)
ENV_ASSUMPTION        - assumed a dep/path/OS that isn't in target env
VACUOUS_TEST          - caught by G-RED-2/G-GREEN-3
TEST_GAMING           - modified/deleted tests to pass
INCOMPLETE            - partial implementation, criteria unmet
OSCILLATION           - ladder cycled without progress
BUDGET_EXHAUSTED      - ran out of tokens/wall clock
CONTEXT_OVERFLOW      - assembler could not fit required context
DECODE_FAILURE        - grammar violation / truncation / repetition loop
ORACLE_GAP            - passed our gates, failed hidden oracle  (→ gate_gap)
```

Each category maps to a specific class of fix:
`API_HALLUCINATION` → strengthen LSP tooling and symbol gating.
`ENV_ASSUMPTION` → put the target-env spec earlier in the prompt and add a
pre-flight dependency check.
`ORACLE_GAP` → add a gate; this is how the battery grows, and it should grow
*only* from observed gaps, never from speculation.
`OSCILLATION` → fix the ladder or the gate's remediation text.

## 8. Reporting

`nightshift eval report --compare default exp/017` produces a static HTML page
(offline, self-contained):

- headline table: accept_rate, gate_gap, cost, with variance bars
- per-task grid, colour-coded, click-through to trajectory
- per-gate first-pass rates, sorted by how much they cost you
- failure taxonomy stacked bar, diffed against baseline
- token/wall budget breakdown by role and by state
- regression list: tasks that passed in baseline and fail in the variant — **this is
  the list you read first**

## 9. Optional Phase 7: learning from your own trajectories

Once the eval harness produces many verified-good trajectories, you have a
rejection-sampled dataset for free — and it's fully offline:

1. Harvest `(assembled_context → artifact)` pairs from runs that passed all gates
   *and* the hidden oracle.
2. Filter aggressively: only first-pass successes, deduplicated, balanced by role
   and domain.
3. LoRA fine-tune per role (Unsloth / LLaMA-Factory) on a role-specific mixture.
   Role-specialised LoRA adapters are cheap to swap at inference (llama.cpp
   supports adapter hot-loading), so this preserves the "different model per agent"
   goal at near-zero memory cost — arguably the *right* way to get genuinely
   different agents on one laptop.
4. Evaluate the adapter with the same harness against the holdout set. If it
   doesn't beat the base model on holdout, throw it away.

Deliberately last: the scaffold will give you far more than fine-tuning will, and
fine-tuning a moving target wastes the effort. But the data collection is free from
day one, so **log trajectories in a training-ready format immediately** even if you
never use them.
