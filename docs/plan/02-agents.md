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

### 2.10 Specialist roles (Phase 5)

- **Reverse Engineer (`re`)** — owns binary-analysis stories. Model class CODER
  with a domain playbook. Tools: Ghidra headless, rizin/r2pipe, capa, objdump,
  gdb/pwndbg, angr. Output artifact: `AnalysisReport` with function-level findings,
  recovered structures, and a *reproducible script* — the gate re-runs the script
  and diffs the output, so "I analysed it" is provable.
- **Vulnerability Researcher (`vr`)** — owns hypothesis→harness→triage loops.
  Output: `VulnFinding` with a **proof-of-crash artifact** (input file + ASAN
  trace + reproduction script). No PoC, no finding. This is the same
  provenance principle applied to security work.

## 3. Model routing

Roles name a **class**; a routing table binds classes to endpoints. This keeps the
roster portable across hardware.

```yaml
model_classes:
  REASONER: { endpoint: local, model: qwen3-30b-a3b-instruct, ctx: 32768 }
  CODER:    { endpoint: local, model: qwen3-coder-30b-a3b,     ctx: 32768 }
  CHEAP:    { endpoint: local, model: qwen3-4b-instruct,       ctx: 16384 }
  JUDGE:    { endpoint: local, model: qwen3-30b-a3b-instruct,  ctx: 16384,
              seed_offset: 7919 }   # different seed ⇒ decorrelated from CODER
```

- With ~2 resident models, `REASONER` and `JUDGE` share weights but differ in seed,
  temperature, system prompt, and — critically — context. Independence of *context*
  does most of the work; independence of *weights* is a bonus you buy with RAM.
- `CHEAP` handles classification, extraction, summarisation, the comprehension
  probe, and the Scrum Master. Keeping a 4B resident alongside a 30B MoE is cheap
  and removes a lot of swap churn.
- The router owns a **queue with priorities** so a cheap probe never blocks the
  critical path, and a **swap policy** that batches all pending CODER work before
  swapping to REASONER. Model swaps are the dominant latency cost on a laptop;
  the scheduler should be swap-aware. See [05](05-model-serving-offline.md).

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
4. **Stable prefix ordering** for prompt-cache reuse (see [05](05-model-serving-offline.md)).
5. Every assembler is unit-tested for *negative* containment: "reviewer context
   must not contain `impl_rationale`".
