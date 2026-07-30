# 03 — Verification: The Gate Battery

This is the core of the system. Build it **before** most of the agents.

Everything here follows from principle P3: *provenance or it didn't happen*. Agents
cannot report results; only runners produce Records, and gates read Records.

## 1. Your four failure modes, mechanically killed

### F1 — Empty or vacuous unit tests

Five independent checks. Each is cheap; together they leave essentially no room.

**G-RED-1 · Red proof (the strongest, and free).**
Every new test must be executed against the **pre-patch tree** and must **fail**,
and the failure message is recorded in a `RedProofRecord`. A test that passes
before the implementation exists is not testing the implementation.

Refinement that matters: the failure must be a *meaningful* failure. Classify it:
`assertion_failure` (good), `not_implemented` (acceptable for stub-driven design),
`import_error` / `syntax_error` / `fixture_error` (rejected — the test isn't
failing for the right reason). Store the classification; gate on it.

**G-RED-2 · AST vacuity check.** Per test function, reject if any hold:
- zero assertions (`assert`, `pytest.raises`, `EXPECT_*`/`ASSERT_*`, `assert_*` in bats)
- only tautological assertions (`assert True`, `assert 1 == 1`, `assert x == x`)
- constructs objects but asserts nothing about them
- asserts only on literals, with no data-flow path from a symbol under test
  (implemented as a small dataflow walk over the test AST: at least one assertion
  operand must derive from a call into the module under test)
- test body is `pass` / `...` / only a docstring
- `@pytest.mark.skip` / `GTEST_SKIP` without an approved, referenced justification

**G-RED-3 · Criterion coverage.** Every `AcceptanceCriterion` must be referenced by
≥1 test (`# criterion: STORY-12/AC-3` tag, machine-parsed). Uncovered criterion →
fail. Test referencing a nonexistent criterion → fail.

**G-GREEN-3 · Mutation score on the diff.** Run mutation testing scoped to the
changed lines (`mutmut` for Python, `mull` or a clang-plugin mutator for C++;
for Bash, a small mutation harness that flips comparisons/exit codes). Gate:
`killed / (killed + survived) ≥ threshold` on changed lines, and every surviving
mutant is reported with its location so the ladder can feed it back as a concrete
task: *"this mutant survives at foo.py:42 — write a test that kills it."*

Mutation testing is the check that vacuous tests cannot survive. It's expensive, so
scope it to the diff and cache by `(tree_sha, file)`.

**G-GREEN-4 · Diff coverage.** Branch coverage on changed lines via `diff-cover` /
`gcovr --filter`. Line coverage alone is insufficient and easily gamed.

### F2 — Features that don't work in the target environment

**Target Environment Contract.** A declarative spec, versioned in the repo:

```yaml
target_env:
  id: te-linux-x86_64-glibc2.36
  base_image: localhost/nightshift/te-debian12:2026-07
  arch: x86_64
  toolchain: { cc: gcc-12, cxx: g++-12, cmake: "3.25", python: "3.11" }
  runtime_deps: [libssl3, zlib1g]
  absent: [network, dev-headers, compilers]   # runtime image is not the build image
  resources: { mem_mb: 2048, cpus: 2 }
```

**G-INTEGRATE-1 · From-scratch build.** Fresh clone of the story branch into a
pristine container built from `base_image`, no caches, no network
(`--network=none`), build from zero. Any implicit dependency on the dev machine
surfaces here and nowhere else.

**G-INTEGRATE-2 · Runtime-image separation.** The built artifact is copied into the
*runtime* image (no compilers, no dev headers, no test deps) and must still run.
This catches "works because pytest happened to be installed".

**G-DEMO-1 · Recorded demonstration.** The acceptance runner executes each
`AcceptanceCriterion.observation` inside the runtime image and records an
`asciinema` cast plus structured results. **No cast, no transition.** The cast is
shipped in the morning report so you can watch the feature work in ten seconds
instead of reading a claim that it does.

**G-DEMO-2 · Resource-constrained run.** Run the demo under the declared limits
(`mem_mb`, `cpus`, and a wall-clock cap). Features that only work with unlimited
memory are not features.

**G-DEMO-3 · Cold-start check.** Demo runs in a container started fresh, with no
state from previous runs, and (where applicable) twice — to catch
first-run-only and second-run-only bugs, which are both common.

### F3 — Tests not actually run

This one is structural rather than a check:

- **Agents have no ability to run tests.** `run` is allowlisted per role and
  `pytest`/`ctest`/`bats` are not on any agent's allowlist. Only the harness's test
  runner executes them, in the sandbox, and it writes the `TestRunRecord`.
- **Records are attested** (HMAC over `tree_sha, cmd_sha, exit_code, stdout_sha`
  with a per-run key the agents never see). A gate that receives an unattested
  record raises.
- **Claim stripping.** `strip_unbacked_claims` (see [01](01-architecture.md) §6)
  nulls any result-claim field in an artifact that lacks a backing Record, and
  emits a `hallucinated_claim` event. Hallucination rate per role is a headline
  metric in the eval harness — if a prompt change makes a role start fabricating,
  you see it in the dashboard.
- **Tree binding.** `TestRunRecord.tree_sha` must equal the sha of the tree the gate
  is evaluating. Stale results cannot be reused across a patch. This also prevents
  the subtler failure: passing tests from *before* the last edit.

### F4 — Tests a human can't read

**G-RED-4 · Deterministic readability rules** (AST-checked, thresholds in the
playbook):
- Test name matches `test_<subject>_<condition>_<expected_behaviour>`; ≥4 words;
  no `test_1`, `test_it_works`, `test_foo`.
- Arrange/Act/Assert or Given/When/Then structure detectable (blank-line separated
  sections, or explicit comments; configurable per language).
- **No control flow in tests** — no `for`, `while`, `if` in a test body. Loops
  become parametrised cases; conditionals become separate tests.
- ≤ N assertions per test (default 4) and all asserting one behaviour.
- No unexplained magic literals: numeric/string literals other than a small
  allowlist must be bound to a named constant or a fixture.
- Every assertion has a failure message or uses an assertion form that produces a
  self-describing diff.
- Fixtures/mocks named for their role (`stub_clock`, not `m1`).
- Test file ≤ N lines; per-test body ≤ 25 lines.

**G-RED-5 · Comprehension probe** — the interesting one. A CHEAP model, with a
**fresh context containing only the test function and its imports** (never the
implementation, never the story), is asked: *"In one sentence, what behaviour does
this test verify?"* The restatement is compared to the linked
`AcceptanceCriterion` text by a semantic similarity check (local embedding model,
plus a JUDGE-model agreement call when the score is borderline).

Low score ⇒ the test does not communicate its intent ⇒ rework, with the probe's
(wrong) restatement handed back as feedback: *"a reader concluded this test checks
X; it should check Y."* That feedback is unusually actionable, and it's a direct
proxy for the thing you actually care about: can a human read it.

**G-REVIEW-3 · Reviewer scorecard on `test_readability`** must be ≥ threshold, with
`file:line` evidence per finding.

## 2. Full gate battery

Gate IDs are stable and appear in commit trailers, event logs, and the morning
report.

### SHAPED
| ID | Check |
| -- | ----- |
| G-SHAPE-1 | Every story has ≥1 acceptance criterion with a machine-checkable `observation` |
| G-SHAPE-2 | Story fits budget heuristics (est. touched files ≤ N, criteria ≤ M) else split |
| G-SHAPE-3 | No criterion duplicates another; no criterion restates an implementation detail |
| G-SHAPE-4 | Out-of-scope list non-empty (forces the PO to bound the work) |

### ARCHITECTED
| ID | Check |
| -- | ----- |
| G-ARCH-1 | Contract declares every public symbol the criteria require |
| G-ARCH-2 | Declared file set doesn't collide with an in-flight story (file-lock table) |
| G-ARCH-3 | ADR records ≥2 options considered and explicit consequences |
| G-ARCH-4 | `solid_rationale` present per module |
| G-ARCH-5 | Contract signatures parse in the target language (real syntax check, not prose) |

### CONTRACTED
| ID | Check |
| -- | ----- |
| G-CONTRACT-1 | Each criterion bound to a planned test id in the `TestPlan` |
| G-CONTRACT-2 | Test plan includes ≥1 negative/boundary case per criterion |
| G-CONTRACT-3 | Property-based test proposed where the contract states an invariant |

### RED
G-RED-1 … G-RED-5 as above, plus:
| ID | Check |
| -- | ----- |
| G-RED-6 | Diff touches only test files (+ declared stubs) |
| G-RED-7 | Full pre-existing suite still passes (new tests didn't break the world) |

### GREEN
| ID | Check |
| -- | ----- |
| G-GREEN-1 | All tests pass in the target-env container (`TestRunRecord`, tree-bound) |
| G-GREEN-2 | No test file modified since `RED` (diff check against the RED commit) |
| G-GREEN-3 | Mutation score on changed lines ≥ threshold |
| G-GREEN-4 | Branch diff-coverage ≥ threshold |
| G-GREEN-5 | **Symbol resolution**: every external symbol referenced by the patch resolves via LSP (`SymbolRecord`). Kills API hallucination outright |
| G-GREEN-6 | Type check clean (`mypy --strict` / compiler `-Wall -Wextra -Werror`) |
| G-GREEN-7 | Lint clean (ruff / clang-tidy / shellcheck), zero new suppressions without justification |
| G-GREEN-8 | No new TODO/FIXME/`XXX` without a linked story id |
| G-GREEN-9 | Sanitizer build passes for C++ (ASAN+UBSAN); no new leaks |

### REFACTORED
| ID | Check |
| -- | ----- |
| G-REFACTOR-1 | Entire GREEN battery still passes |
| G-REFACTOR-2 | Zero test files changed |
| G-REFACTOR-3 | Complexity does not regress: max cyclomatic, max function length, duplication % all ≤ pre-refactor values |
| G-REFACTOR-4 | Public API unchanged vs Contract (signature diff is empty) |

### REVIEWED
| ID | Check |
| -- | ----- |
| G-REVIEW-1 | Zero `blocker` findings; `major` findings ≤ threshold (default 0) |
| G-REVIEW-2 | Every finding has a resolvable `file:line` |
| G-REVIEW-3 | Scorecard dimensions all ≥ threshold |
| G-REVIEW-4 | DevSecOps: zero high/critical scanner findings unsuppressed; each suppression has a rationale independently confirmed by the Reviewer |
| G-REVIEW-5 | Contract adherence: implemented public surface == Contract surface |
| G-REVIEW-6 | Threat model: every untrusted input has a referenced test |

### INTEGRATED
| ID | Check |
| -- | ----- |
| G-INTEGRATE-1 | From-scratch build in pristine container, no network, no cache |
| G-INTEGRATE-2 | Runtime-image separation check |
| G-INTEGRATE-3 | Full CI pipeline green (all stages) |
| G-INTEGRATE-4 | Merge to integration branch is clean and the suite passes *post-merge* (catches semantic conflicts between parallel stories) |
| G-INTEGRATE-5 | Build is reproducible: two builds yield identical artifact hashes (or a documented, justified exception) |

### DEMONSTRATED
G-DEMO-1 … G-DEMO-3 as above, plus:
| ID | Check |
| -- | ----- |
| G-DEMO-4 | Every criterion's `observation` evaluated with a pass result in the runtime image |

### DOCUMENTED
| ID | Check |
| -- | ----- |
| G-DOC-1 | Every public symbol has a docstring/doc comment that states behaviour, not restating the name |
| G-DOC-2 | README quickstart commands **executed verbatim** and exit 0 |
| G-DOC-3 | `--help` output executed, non-empty, covers every flag the code defines (parsed from argparse/clap/getopts and cross-checked) |
| G-DOC-4 | Every documented example is executed; outputs match documented output |
| G-DOC-5 | Runbook commands executed successfully |
| G-DOC-6 | Changelog entry present and references the story |

### ACCEPTED
| ID | Check |
| -- | ----- |
| G-ACCEPT-1 | PO maps every criterion → specific Record id; unmapped criterion fails |
| G-ACCEPT-2 | Evidence bundle complete (build, test, coverage, mutation, scan, demo, docs records all present and attested) |
| G-ACCEPT-3 | Zero open `blocker`/`major` findings |
| G-ACCEPT-4 | Story branch merges cleanly to integration; post-merge suite green |

## 3. Gate implementation notes

- Gates are **pure functions**: `(story, artifacts, records, thresholds) → GateResult`.
  No side effects, no I/O. Runners do I/O and produce Records; gates evaluate. This
  makes gates trivially unit-testable, and you should write those tests with
  synthetic evidence fixtures (including deliberately vacuous test files — build a
  corpus of "bad tests we must catch" as a permanent regression suite for the gate
  battery itself).
- Every `GateResult` carries `remediation`: a machine-generated, concrete
  instruction for the next agent attempt ("mutant survives at `parser.cpp:88`
  — `<` → `<=`; add a boundary test"). Gate feedback quality is what determines
  whether attempt 2 succeeds; treat it as a first-class product surface.
- Thresholds live in the playbook and are swept by the eval harness. Do not
  hard-code them.
- Gates cache by `(gate_id, tree_sha, thresholds_hash)`. Mutation testing and
  from-scratch builds are the expensive ones; caching them across ladder retries
  that didn't touch the relevant files is a large win.
- **Gate order matters**: run cheapest-first and short-circuit. Typical ordering:
  AST checks (ms) → lint/type (s) → unit tests (s) → coverage (s) → symbol
  resolution (s) → mutation (min) → from-scratch build (min) → demo (min).

## 4. Anti-gaming

Small models will find the shortest path to a green gate. Assume adversarial
pressure without adversarial intent, and close the obvious holes explicitly:

| Exploit | Countermeasure |
| ------- | -------------- |
| Weaken a test to make it pass | G-GREEN-2 (zero test edits after RED); test-file diff monitored across the whole story |
| Add `# pragma: no cover` / `# noqa` / `NOLINT` | New suppressions counted as findings; each requires justification confirmed by an independent role |
| Delete a failing test | Test-count monotonicity check per file; deletions require an explicit `TestRemoval` artifact with rationale |
| Assert on the implementation instead of behaviour | Reviewer rubric + comprehension probe (a test that mirrors the implementation restates the implementation, and the probe's restatement won't match the criterion) |
| Kill mutants with an over-broad assertion | Mutation *and* comprehension probe *and* assertion-specificity check |
| Make the demo trivially succeed | Criteria observations are authored at `SHAPED`, before any code exists, and are immutable afterwards without a PO change-request artifact |
| Loosen thresholds | Playbook is version-controlled; the orchestrator refuses to load a playbook whose thresholds differ from the run's pinned hash |
| Stub the feature and satisfy the unit tests | G-DEMO-* runs against the runtime image with no test doubles present |

## 5. What is deliberately *not* gated

Be honest about the limits so you calibrate trust:

- **Whether the design is good.** Gates check adherence to a contract, not the
  wisdom of the contract. Architect quality is the main residual risk. Because
  inference is now abundant ([05](05-inference-and-topology.md) §4), the partial
  mitigation is **self-consistency**: sample the Architect k times independently and
  surface disagreement to the Manager and to you, rather than shipping one
  unexamined design. It's cheaper than being wrong, but it is a mitigation, not a
  gate — the design is still the thing to review yourself in the morning.
- **Whether the feature is the right feature.** That's your Charter, and the PO
  agent only refines it.
- **Deep semantic security.** Scanners plus fuzzing catch a class of bugs, not all
  of them.
- **Performance**, unless a criterion states a threshold. Add
  `metric_threshold` observations when you care.
