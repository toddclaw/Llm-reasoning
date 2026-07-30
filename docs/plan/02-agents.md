# 02 — The Scrum Roster

## 1. Agent contract

Every role is a row in the role registry, fully declarative:

```python
@dataclass(frozen=True)
class Role:
    id: str                       # "tdd-dev"
    model_class: ModelClass       # REASONER | CODER | CHEAP | JUDGE
    system_prompt: Path
    input_kinds: tuple[str, ...]  # artifact kinds it may read
    output_schema: type[Artifact]
    tools: frozenset[str]         # allowlist
    run_allowlist: tuple[str, ...]# shell commands it may execute, if any
    assemble_context: Callable[[Story, State, int], dict]
    sampling: Sampling            # temp, top_p, repeat_penalty, max_tokens
    context_budget_tokens: int    # hard cap; assembler must fit or summarise
    states: tuple[State, ...]     # which transitions it handles
```

Two invariants:

- **`assemble_context` is Python, not a prompt.** It queries the blackboard and
  returns exactly the fields the template needs. This is where context isolation is
  actually enforced, and it is unit-testable — write tests asserting that the
  reviewer's context does *not* contain the implementer's rationale.
- **`output_schema` drives a GBNF grammar.** The model physically cannot emit a
  malformed artifact.

## 2. The roster

> The roster below is the **BUILD path**. The **INVESTIGATE path** (RE/VR) uses a
> smaller roster — Analyst, Verifier, Reporter, Manager — over the same runtime and
> contract; see [10-dual-path-and-existing-repos.md](10-dual-path-and-existing-repos.md).
> The path is chosen at session start (`--path build|investigate`).

### 2.0 Codebase Cartographer (`cartographer`) — BUILD, existing repos

- **Model class:** REASONER, large context. **Runs once per repo**, cached and
  refreshed incrementally on file-hash change — not once per story.
- **Owns state:** `INTAKE → MAPPED` (a new first state, since almost all work is on
  existing codebases).
- **Outputs:** `CodebaseMap` — modules and inferred responsibilities, conventions,
  build/test entry points, dependency graph, hotspots, style exemplars, discovered
  invariants, and `danger_zones` (untested/vendored/generated code).
- A **digest** of the map is injected into the stable prompt prefix of every
  downstream agent ([05](05-inference-and-topology.md) §5), so the whole roster
  inherits repo awareness at near-zero marginal cost via prefix caching. Its
  `conventions` feed the per-repo style gates and its `exemplars` feed the context
  assemblers. Full detail in [10](10-dual-path-and-existing-repos.md) §3.

### 2.1 Product Owner (`po`)

- **Model class:** REASONER. **Temp:** 0.3.
- **Owns states:** `INTAKE → SHAPED`, and the final `DOCUMENTED → ACCEPTED` sign-off.
- **Inputs:** the human request, the Charter, existing repo README/docs.
- **Outputs:** `Charter`, `Story[]` with `AcceptanceCriterion[]`.
- **The hard part:** acceptance criteria must be **observable and mechanically
  checkable**. The PO's output schema forbids criteria without an
  `observation: {kind: cli_exit|stdout_match|file_exists|http_status|test_passes|
  metric_threshold, spec: ...}`. "The code should be maintainable" cannot be
  expressed in the schema, which is the point. Soft qualities are handled by the
  Reviewer's rubric, not by acceptance criteria.
- **Sign-off is not a vibe check.** At `ACCEPTED`, the PO is shown *only* the
  criteria and the corresponding Records, and must map each criterion to the
  evidence that satisfies it. Unmapped criterion → gate failure, regardless of what
  the PO says.

### 2.2 Scrum Master (`sm`)

- **Model class:** CHEAP. **Temp:** 0.
- **Owns:** no state transitions. Runs as a periodic *process auditor*.
- Reads the event log and answers narrow questions: is a story oscillating? is a
  ladder rung being skipped? is a gate being retried with an identical diff? are
  we spending disproportionate budget on one epic?
- **Most of what a Scrum Master does here is code, not a model** — oscillation
  detectors and budget accounting are deterministic. The agent exists for the
  residual: writing a human-readable impediment summary for the morning report and
  proposing which parked story to surface first.
- Deliberately low-power. Do not let this role make routing decisions.

### 2.3 Architect (`architect`)

- **Model class:** REASONER. **Temp:** 0.2. Largest context budget (16k).
- **Owns states:** `SHAPED → ARCHITECTED`, and ladder rung 4 (`revisit ADR`).
- **Outputs:** `ArchDecision` (ADR), `Contract`.
- The `Contract` is the most important artifact in the system. It contains:
  - module/file layout and which files each story may touch (drives the file-lock
    table and enables parallel stories),
  - **exact public signatures** (Python: full type annotations; C++: header
    declarations; Bash: usage strings),
  - invariants and the error taxonomy,
  - data schemas (pydantic / JSON Schema / struct definitions),
  - explicit non-goals.
- Contract-first is what lets a small model implement well: it removes the design
  degrees of freedom that small models fumble, leaving local transformation, which
  they're good at.
- **SOLID is enforced here, not in review.** The architect's output schema requires
  a `solid_rationale` per module (which responsibility, what's the extension seam,
  what's substitutable, which interfaces are segregated, what's injected). The
  Reviewer later checks the *code* against these declared seams — a concrete,
  checkable question, unlike "is this SOLID?".
- Also emits `revisit_triggers`: conditions under which this ADR should be
  reopened. The ladder consults these instead of improvising.

### 2.4 TDD Developer (`tdd-dev`)

The workhorse. Split into **three distinct invocations with separate contexts**,
because merging them is where "wrote the test to match the code I already wrote"
comes from:

| Invocation | State | Sees | Must not see |
| ---------- | ----- | ---- | ------------ |
| `tdd-dev:test` | `CONTRACTED → RED` | Contract, criteria, existing test conventions, docs | Any implementation body |
| `tdd-dev:impl` | `RED → GREEN` | Contract, the failing tests, failure output, LSP diagnostics | The test author's rationale |
| `tdd-dev:refactor` | `GREEN → REFACTORED` | Full code, review rubric, complexity metrics | — |

- **Model class:** CODER for `impl`/`refactor`; REASONER for `test` (test design is
  a reasoning task; test *writing* is not the bottleneck).
- `tdd-dev:test` writes tests **only**; the gate rejects the transition if the diff
  touches non-test files (with a narrow allowance for creating empty
  interface stubs so the tests can import — those stubs must raise
  `NotImplementedError` / be pure declarations, checked by AST).
- `tdd-dev:impl` operates under best-of-N on retry: N candidate patches at temp
  0.7, each scored by the full deterministic gate battery, best wins. This is the
  System-2 search mechanism, and it is the single biggest quality lever available
  for a small model. It's also the biggest cost — enable it from attempt 2 onward
  only.
- `tdd-dev:refactor` must not change behaviour: the gate re-runs the entire
  `GREEN` battery plus a check that no test file changed.

### 2.5 Reviewer / Craftsperson (`reviewer`)

- **Model class:** JUDGE (a different model instance from the implementer wherever
  memory allows — independence matters more than capability here). **Temp:** 0.
- **Owns:** `REFACTORED → REVIEWED` (jointly with `devsecops`).
- **Fresh context.** Sees the diff, the Contract, and the rubric. Never sees the
  implementer's reasoning. A critic that has read the author's justification
  approves it.
- Output is a structured scorecard, not prose:
  ```
  ReviewVerdict:
    dimensions: {naming, cohesion, coupling, error_handling, test_readability,
                 duplication, comment_value, contract_adherence, solid_seams}
      → each: score 1-5 + evidence: [file:line] + fix_hint
    findings: [{severity: blocker|major|minor|nit, rule_id, file, line, why, fix}]
    verdict: pass | rework
  ```
- Every finding **must** carry a `file:line`. Findings without a resolvable
  location are dropped automatically — this kills the small-model habit of generic
  advice ("consider adding error handling").
- Deterministic pre-filters run first and are *not* the model's job: complexity
  (radon/lizard), duplication (jscpd), function length, parameter count, import
  cycles. The model only judges what tools cannot.

### 2.6 DevOps (`devops`)

- **Model class:** CODER. **Temp:** 0.2.
- **Owns:** `REVIEWED → INTEGRATED`, plus ownership of the target-env image
  definition and the CI pipeline.
- Responsibilities:
  - keep the offline CI definition green (see [06](06-domain-playbooks.md)),
  - **from-scratch verification**: fresh clone into a pristine target-env container,
    build with no dev cache, run the full suite. This is the F2 killer,
  - reproducibility: pinned toolchains, hermetic builds, no network in the build,
  - the `Runbook` doc — and every command in it is *executed* by the gate, so a
    runbook that doesn't work fails the gate.
- Wider `run_allowlist` than other roles, still an allowlist.

### 2.7 DevSecOps (`devsecops`)

- **Model class:** REASONER. **Temp:** 0.1.
- **Owns:** co-signs `REFACTORED → REVIEWED`; blocks on `blocker` findings.
- Runs and *interprets* the scanners: semgrep (with local rulepacks), bandit,
  gitleaks, `cargo-audit`-equivalents from a local advisory DB snapshot,
  clang-tidy security checks, ASAN/UBSAN builds, dependency license/vuln check
  against an offline advisory mirror.
- The model's job is triage and fix-proposal, not detection — detection is tools.
  It must classify each finding as `true-positive | false-positive | needs-human`
  with a justification referencing the code, and false-positive claims require a
  suppression comment with a rationale that the Reviewer independently checks.
- Owns the **threat-model note** per epic: trust boundaries, untrusted inputs,
  and for each one, which test exercises it. Missing coverage of an untrusted input
  is a `major` finding.

### 2.8 UX (`ux`)

- **Model class:** REASONER. **Temp:** 0.4.
- **Owns:** `DEMONSTRATED → DOCUMENTED` jointly with the dev.
- For CLI/library work — which is most of your stated domain — UX means:
  - `--help` output: complete, accurate, examples that are *executed by the gate*,
  - error messages: actionable, no stack traces to end users, consistent taxonomy,
  - exit codes: documented and tested,
  - output formats: stable, machine-parseable option available,
  - README quickstart whose commands are executed verbatim by the gate.
- The distinguishing mechanic: **the UX agent reviews the `DemoRecord` cast**, not
  the source. It sees what a user sees. Its findings reference cast timestamps.

### 2.9 Manager (`manager`)

- **Model class:** REASONER. **Temp:** 0.3.
- **Owns:** nothing in the happy path. Handles: ladder rung 5 decisions (park vs
  decompose vs re-plan), cross-story conflict resolution, nightly re-prioritisation,
  and authoring the morning report narrative.
- Explicitly *not* a router. Routing is the state machine. If the Manager is being
  invoked frequently, that is a signal the gates or the Architect's decomposition
  are wrong, and the Scrum Master should surface it.

### 2.10 INVESTIGATE-path roster (RE/VR)

The INVESTIGATE path runs a distinct, smaller roster over the same runtime — see
[10-dual-path-and-existing-repos.md](10-dual-path-and-existing-repos.md) for its
state machine and artifacts. Summary:

- **Analyst (`analyst`)** — CODER class + RE domain playbook. Emits *scripts* (Ghidra
  headless, rizin/r2pipe, capa, angr) that the harness runs; the attested script
  output is the Evidence. Produces `Finding`s that must cite that evidence. A claim
  with no producing script is inadmissible.
- **Verifier (`verifier`)** — JUDGE class, fresh context, never sees the Analyst's
  reasoning. Independently regenerates a reproduction for each `Finding`; the harness
  re-runs it and a claim that doesn't reproduce is demoted to a hypothesis. The
  analysis-side analogue of the Reviewer.
- **Reporter (`reporter`)** — REASONER class. Writes the `AnalysisReport`; every
  sentence links to an Evidence/Verification id, and the mandatory `unknowns` list
  is the honest analogue of a parked story.
- **Vulnerability findings** on this path carry a **proof-of-crash** (input blob +
  sanitizer trace + reproduction script) and a fix-verification record. No PoC, no
  finding — the same provenance principle as everywhere else.

## 3. Model routing

Roles name a **class**; a routing table binds classes to endpoints. The class
abstraction is kept even though the hardware is now a fixed H200 rack — it's what
lets the roster, the eval sweeps, and the prompts stay independent of which
checkpoint sits behind each class.

```yaml
model_classes:
  REASONER: { endpoint: rack, model: Qwen3.5-397B-A17B-FP8,  ctx: 128000 }
  CODER:    { endpoint: rack, model: Qwen3-Coder-Next-FP8,   ctx: 128000 }
  JUDGE:    { endpoint: rack, model: Qwen3.5-397B-A17B-FP8,  ctx:  64000 }
  CHEAP:    { endpoint: rack, model: <small Qwen3 instruct>, ctx:  32000 }
  EMBED:    { endpoint: rack, model: <bge-m3 / qwen3-embed>, ctx:   8000 }
```

- Both large models are **resident simultaneously** on the rack (vLLM, separate GPU
  groups), so there is **no swapping** — the laptop-era swap policy, swap batching,
  and `swaps_per_task` metric are deleted. See
  [05-inference-and-topology.md](05-inference-and-topology.md).
- `JUDGE` shares the REASONER checkpoint but runs with an offset seed and, more
  importantly, an independent context that never contains the author's rationale.
  Context independence does most of the work; here weight-sharing costs nothing.
- **The binding constraint is now the laptop's compile/test capacity, not
  inference.** The router optimises for gate-runner throughput, not token cost:
  it fans out best-of-N generations freely, then a cheap static pre-filter culls
  candidates before the expensive gate battery runs. See [05](05-inference-and-topology.md) §4.
- `CHEAP` handles classification, extraction, summarisation, the comprehension
  probe, and the Scrum Master.

## 4. Context assembly policy

Per-role budgets, enforced by the assembler (which raises rather than silently
truncating):

| Role | Budget | Composition |
| ---- | ------ | ----------- |
| `po` | 8k | request + charter + repo README + existing criteria |
| `architect` | 16k | charter + stories + repo tree summary + relevant ADRs + interface index |
| `tdd-dev:test` | 8k | contract slice for this story + criteria + 2 exemplar tests from repo + conventions |
| `tdd-dev:impl` | 12k | contract slice + failing tests + failure output + LSP diagnostics + relevant symbol spans |
| `reviewer` | 10k | diff + contract slice + rubric + deterministic metric report |
| `devsecops` | 10k | diff + scanner findings + threat-model note |
| `ux` | 6k | demo cast transcript + help output + README |
| `manager` | 12k | story states + ladder history + budgets + blocked questions |

Assembly rules:

1. **Slices, not files.** Use LSP to pull the exact symbol spans referenced by the
   contract. Whole-file dumps are banned above 200 lines.
2. **Failure evidence goes last** and is never summarised. The literal compiler
   error / assertion diff is the highest-value token spend in the system.
3. **Exemplars beat instructions.** For style-shaped tasks (test readability,
   naming, error messages), include 1–2 *good examples from this repo* rather than
   another paragraph of rules. Small models imitate far better than they follow.
4. **Stable prefix ordering** for prompt-cache reuse (see [05](05-inference-and-topology.md)).
5. Every assembler is unit-tested for *negative* containment: "reviewer context
   must not contain `impl_rationale`".
