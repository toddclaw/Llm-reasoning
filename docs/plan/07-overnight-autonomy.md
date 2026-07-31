# 07 — Overnight Autonomy

The goal: start it at 22:00, walk away, and at 07:00 find finished work plus an
honest account of what didn't finish and why.

The failure to avoid is not "it didn't finish everything." It's "it burned nine
hours on one story" or "it says everything is done and it isn't."

## 1. The escalation ladder

Every gate failure invokes the ladder for that story. Rungs are attempted in order;
each rung has a max-attempt count from the playbook.

| Rung | Action | Default attempts | Notes |
| ---- | ------ | ---------------- | ----- |
| 1 | **Retry with evidence** — same role, same model, gate's `remediation` + verbatim failure output appended | 2 | Cheapest and most often sufficient. Prompt-cache friendly |
| 2 | **Widen context** — pull in additional symbol spans, related tests, relevant docs chunks | 1 | For `CONTEXT`-shaped failures |
| 3 | **Escalate model / search** — best-of-N candidate patches (N=4, temp 0.7) scored by the deterministic gate battery, best wins | 1 | The System-2 search rung. Expensive; this is where the token budget goes |
| 4 | **Decompose** — Architect splits the story into smaller stories; original becomes an epic | 1 | Most effective rung for `INCOMPLETE` failures |
| 5 | **Revisit design** — Architect reopens the ADR if a `revisit_trigger` matches | 1 | Prevents grinding against a bad contract |
| 6 | **Park** — write a `BlockedQuestion`, release the worktree, move to the next story | — | Terminal |

Rules:
- The ladder never repeats a rung that produced an identical tree sha.
- Rung 3 is skipped for gates whose failures are deterministic and non-searchable
  (e.g. a missing doc file) — the playbook maps gate families to eligible rungs.
- Total per-story attempt budget caps the whole ladder regardless of rung.

## 2. Progress detectors

Deterministic, running continuously in the orchestrator:

| Detector | Trigger | Action |
| -------- | ------- | ------ |
| **Identical diff** | Two attempts produce the same tree sha | Skip to next ladder rung immediately |
| **Oscillation** | Tree shas cycle (A→B→A) within a story | Jump to rung 4 (decompose) |
| **Gate churn** | Same gate fails ≥3 times with the same `detail` fingerprint | Jump to rung 4; log `OSCILLATION` |
| **No-progress** | N attempts without any new gate passing | Jump to rung 5, then park |
| **Budget** | Story exceeds token or wall-clock budget | Park immediately |
| **Global budget** | Run exceeds nightly budget | Finish in-flight gates, park everything else, write report |
| **Decode-failure storm** | >X grammar failures in a window | Reduce schema depth for that role, log a runtime defect, park |
| **Disk/RAM pressure** | Free space or RSS thresholds crossed | Pause scheduling, prune caches, warn in the report |

The Scrum Master agent reads these signals; it does not produce them. Detection is
code, narration is the model.

## 3. Budgets

Three levels, all enforced by the orchestrator. Budgets are expressed primarily in
**gate-runner wall-clock**, not tokens — inference is abundant now, so tokens are
tracked for reporting but rarely bind ([05](05-inference-and-topology.md) §4).

```yaml
budgets:
  run:   { wall_hours: 9,  gate_minutes: 480 }
  epic:  { wall_hours: 4,  gate_minutes: 200 }
  story: { wall_minutes: 90, gate_minutes: 60, attempts: 12 }   # tokens: tracked, not capped
reserve:
  report_minutes: 20      # always leave time to write the morning report
  integration_minutes: 30 # always leave time to merge + verify accepted stories
```

`gate_minutes` is the real constraint: mutation testing, sanitizer builds, and
from-scratch container builds dominate it. Best-of-N widens generation for free but
must be funnelled (static pre-filter → top 1–2 into the full battery) so it doesn't
blow the gate budget — see [05](05-inference-and-topology.md) §4.

The reserve matters: an overnight run that hits the wall at 06:55 with unmerged
work and no report is worse than one that stops at 06:15 cleanly. The scheduler
stops *starting* new stories once remaining time < reserve + median story time.

## 4. Crash resumability

- All state in SQLite with WAL; every transition is a transaction.
- On startup, `nightshift run --resume <run_id>` reconciles: any story in a
  non-terminal state with no running process is rolled back to its last passed gate
  (git reset to that commit) and re-queued.
- The container sandbox is stateless; orphaned containers are reaped by label.
- The model server is supervised and restarted on crash; in-flight requests are
  retried once, then counted as `DECODE_FAILURE`.
- A run must survive a laptop sleep/wake cycle. Test this explicitly — it will
  happen.

## 5. Concurrency plan — inference is abundant, verification is the bottleneck

With both models resident on the rack (no swapping) and continuous batching, LLM
calls are cheap and parallel. The scarce resource is now the **laptop's
compile-and-test capacity** ([05](05-inference-and-topology.md) §4). Scheduling
inverts accordingly: keep the gate runners saturated, fan out inference freely to
feed them.

```
Story A: RED (llm, cheap) ─▶ GREEN gen ×N (llm, parallel) ─▶ [static filter] ─▶ [test+mutation ★]
Story B: REVIEW (llm) ─────────────────────────────────────────────────────▶ [from-scratch build ★]
Story C: fuzz campaign ────────────────────────────────────────────────────▶ (background, ★★)
                                                                       ★ = scarce gate-runner slot
```

The scheduler tags each state with `resource_class ∈ {llm, gate, io}`:

1. **`llm` is not rate-limited by us** — the rack's continuous batching handles
   concurrency. Fan out best-of-N generations and self-consistency samples freely.
2. **`gate` slots are the throttle.** They live on the Proxmox build VM (A17), not
   the laptop; the host-side broker load-balances jobs across however many build VMs
   exist (scaling is a provisioning decision). A cheap static pre-filter runs in the
   agent container and culls best-of-N candidates *before* they consume a scarce
   build-VM slot ([05](05-inference-and-topology.md) §4).
3. Long fuzz/mutation campaigns run in a low-priority background pool with a CPU
   quota so they never starve the interactive gate path.
4. Prefer scheduling work whose next state is `gate`-bound over generating more `llm`
   work that will only queue behind the runners — the goal is a full gate pool, not
   a full inference queue.

## 6. Safety envelope for unattended operation

Non-negotiable defaults for an overnight run:

- The agent container has no internet, no host fs, and no SSH keys — only the
  rack + broker tunnels on its egress allowlist ([05](05-inference-and-topology.md)
  §1). Build/test runs on the build VM and demos on the target VM, both local-net
  only; the *only* internet-capable step in the whole system is manual seeding.
- Agent writes are confined to the story worktree. The orchestrator's own source,
  the playbook, `tasks_oracles/`, and the model weights are read-only mounts.
- **No pushes to any remote, ever** — the container has no SSH keys, so this is
  structural, not a policy (A4). Agents *do* create commits; merges go to a local
  integration branch only. You review and push in the morning.
- No force-push, no history rewriting, no `git clean -x` outside a worktree.
- Untrusted binaries (RE/VR) execute only in a Proxmox target VM with no route back
  to the laptop or the build VM, and only within the authorised `scope.yaml` CIDR
  (A19), enforced by the host-side broker.
- Resource caps: per-container memory/CPU/pids limits, global disk quota for
  evidence with LRU pruning of old runs.
- A hard kill switch: `touch .nightshift/STOP` is checked before every transition;
  the run drains in-flight work and writes the report.

## 7. The morning report

A single self-contained HTML file at `.nightshift/reports/<date>.html`, plus a
terse terminal summary. Designed to be read in five minutes with coffee.

**Section 1 — Verdict.** Stories accepted / parked / failed. Wall-clock and token
spend. Scope of work. Toolchain and model hashes.

**Section 2 — Accepted work.** Per story: the narrative, the acceptance criteria
each mapped to its evidence, the diff stat, and **an embedded asciinema player
showing the feature actually running**. This is the section that builds trust — you
watch the thing work rather than reading a claim.

**Section 3 — Quality dashboard.** Coverage, mutation score, complexity delta,
review scorecards, security findings, doc gate results. Trend against previous
nights.

**Section 4 — Parked stories.** Each with exactly one crisp question and the
context needed to answer it in under a minute. Sorted by how much work they unblock.
*This section is the product.* An agent system that knows precisely what it doesn't
know is far more valuable than one that guesses.

**Section 4b — Seeded from findings** (when an INVESTIGATE run ran). BUILD stories
auto-created from verified findings (A20), each linked to its `Finding` and evidence,
enabled by default but listed here for your veto before the next run — see
[10](10-dual-path-and-existing-repos.md) §1a. On the INVESTIGATE path this section is
replaced by the **Answers** (each `Question` mapped to its findings + evidence) and
the **Unknowns** (what could not be determined, and what data would settle it — the
analysis-side analogue of a parked question).

**Section 5 — Process health** (Scrum Master). Where the time went, which gates
were the bottleneck, which stories oscillated, ladder rung distribution,
hallucinated-claim counts by role. This is your feedback loop for tuning the
playbook.

**Section 6 — Diffs and audit.** Links to branches, full event log, every Record.

Rule for the report: **it never asserts anything not backed by a Record**, and every
claim links to its evidence. The report is generated from the blackboard by code;
the Manager agent writes only the narrative prose sections, and its output is
subject to the same claim-stripping as any other artifact.

## 8. What a good night looks like

Set expectations concretely so you can tell success from failure:

- 3–6 small stories accepted, or 1–2 medium ones.
- 1–3 stories parked with genuinely good questions.
- Zero stories that reached `ACCEPTED` and turn out to be broken when you look.
  If this number is ever non-zero, stop adding features and fix the gate battery —
  that's the `gate_gap` metric doing its job, and it is the only metric that can
  destroy trust in the whole system.
