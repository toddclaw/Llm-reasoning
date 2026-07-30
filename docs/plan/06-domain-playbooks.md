# 06 — Domain Playbooks

A domain playbook binds a language/discipline to concrete tooling: runners,
gate thresholds, prompt fragments, exemplars, and the `run_allowlist`. Adding a
domain must never require touching the orchestrator.

```yaml
# domains/python/playbook.yaml
id: python
detect: ["pyproject.toml", "**/*.py"]
runners:
  build:    ["uv sync --offline --frozen"]
  test:     ["pytest -q --junitxml={junit} --cov --cov-report=xml:{cov}"]
  coverage: ["diff-cover {cov} --compare-branch {base} --fail-under {thr}"]
  mutation: ["mutmut run --paths-to-mutate {changed} --simple-output"]
  lint:     ["ruff check .", "ruff format --check ."]
  types:    ["mypy --strict {pkg}"]
  scan:     ["bandit -r {pkg} -f json", "semgrep --config {rules} --json"]
thresholds: { diff_coverage: 90, mutation_score: 75, max_complexity: 8 }
test_conventions:
  framework: pytest
  naming: "test_<subject>_<condition>_<expected>"
  structure: arrange_act_assert
exemplars: [ "docs/exemplars/python/test_good.py" ]
lsp: pyright
```

## 1. Python

- **Test:** pytest. **Property tests:** hypothesis — required whenever the Contract
  declares an invariant (G-CONTRACT-3). Property tests are unusually good value
  with small models: the model only has to state the invariant, and the framework
  does the hard part of finding the counterexample.
- **Types:** `mypy --strict` as a hard gate. Type errors are the cheapest correctness
  signal available, and a strict-mode failure is far more actionable feedback for
  a small model than a runtime traceback.
- **Mutation:** `mutmut`, scoped to changed files. Cache by file content hash.
- **Lint/format:** ruff (check + format). Format is applied automatically by the
  harness, not by the agent — don't spend model tokens on whitespace.
- **Packaging:** `uv` with a vendored wheelhouse, fully offline, lockfile committed.
- **LSP:** pyright for `symbol_def`/`hover`/`diagnostics` and for G-GREEN-5.

## 2. C++

The hardest domain for a small model, and the one where the harness earns its keep.

- **Build:** CMake with presets; `compile_commands.json` generated and exposed to
  the agent's tools. Ninja. Warnings-as-errors (`-Wall -Wextra -Wpedantic -Werror`).
- **Test:** GoogleTest or Catch2 (pick one per project; GoogleTest if you want
  gMock). CTest as the driver, junit XML output for the record parser.
- **Sanitizers:** a mandatory ASAN+UBSAN build in the GREEN battery, TSAN for
  anything touching threads. This catches the class of bug that small models
  produce most often — lifetime and aliasing errors that pass a naive test.
- **Coverage:** gcov/llvm-cov → `gcovr`, branch coverage, filtered to changed files.
- **Mutation:** `mull` (LLVM-based) if it builds cleanly for your toolchain;
  otherwise a small source-level mutator over the changed lines (relational
  operator swap, boundary shift, return-value replacement, statement deletion) is
  ~300 lines and sufficient. Start with the simple one.
- **Static analysis:** clang-tidy (with `cppcoreguidelines-*`, `bugprone-*`,
  `performance-*`), cppcheck, include-what-you-use.
- **LSP:** clangd. Essential — C++ API hallucination is rampant and clangd
  resolution is the cure.
- **Prompt guidance that measurably helps small models on C++:** always give the
  full header (declarations) in context rather than asking the model to recall an
  API; prefer standard-library solutions; ban raw `new`/`delete` in the domain
  playbook and let the gate enforce it; require RAII; require `const`-correctness
  as a clang-tidy check rather than a review comment.
- **Modern-C++ standard pinned in the target env contract** (e.g. C++20) and stated
  in the stable prompt prefix — models drift toward whatever era dominates their
  training data otherwise.

## 3. Bash

- **Lint:** shellcheck (all warnings as errors), shfmt for formatting.
- **Test:** bats-core, with `assert_*` helpers so the AST vacuity check has
  something to detect.
- **Mandatory preamble** enforced by gate: `set -euo pipefail`, `IFS=$'\n\t'`,
  explicit `trap` for cleanup where temp files are created.
- **Gate additions:** every script has a `usage()` and `--help`, executed by G-DOC-3;
  all variables quoted (shellcheck SC2086); no `eval` without an approved
  justification; exit codes documented and tested.
- Bash is where "works on my machine" hides most easily, so G-INTEGRATE-2 (runtime
  image, minimal utilities, likely no bash-isms available if `/bin/sh` is dash)
  matters more here than anywhere.

## 4. Reverse engineering

**Sandbox first.** Every binary under analysis is untrusted. Analysis runs in a
container with `--network=none`, read-only mount of the sample, a seccomp profile,
no host device access, and a strict wall-clock/memory cap. *Execution* of a sample
(as opposed to static analysis) happens only under `qemu-user` or a disposable
microVM, never in the analysis container, and only when the story explicitly
requests dynamic analysis with a recorded justification.

- **Tooling:** Ghidra headless (`analyzeHeadless` + Python/Java scripts), rizin/r2
  via `r2pipe`, `capa` with local rules, `binwalk`, `objdump`/`readelf`/`nm`,
  `gdb`+`pwndbg`, `angr` for symbolic execution on constrained problems.
- **The key design point: RE work is only agent-tractable when it is scripted.** A
  small model cannot hold a disassembly in its head. So the `re` agent's output
  artifact is an **analysis script plus a report**, and the gate re-runs the script
  and diffs the output against the report. Claims not reproduced by the script are
  stripped (same P3 mechanism as everywhere else).
- **Decomposition pattern** the Architect should apply to RE stories:
  1. triage (file type, packing, imports, strings, `capa` capabilities)
  2. surface map (entry points, exported functions, call graph, candidate
     functions ranked by relevance to the question)
  3. per-function analysis, *one function per LLM call* with decompiler output +
     xrefs + strings for that function only
  4. hypothesis formation (what algorithm/protocol/format is this)
  5. **hypothesis verification** — write a reimplementation or a parser and prove
     it against the real binary's behaviour or against sample data
  6. report with reproducible script
  Step 5 is what makes this real rather than plausible-sounding, and it maps
  perfectly onto the RED/GREEN discipline: a recovered algorithm is "green" when a
  test proves the reimplementation matches ground truth.
- **Eval tasks:** stripped binaries compiled from source you hold (so the source is
  the oracle), crackmes with known keys, format-parsing challenges where the oracle
  is a round-trip test, and "recover this algorithm" tasks scored by differential
  testing against the original.
- **Context tactic:** decompiler output is enormous. Always pass one function at a
  time, with a persistent `note()`-backed symbol dictionary the agent builds up
  (renamed functions, recovered structs) that gets injected into subsequent calls.
  That dictionary *is* the agent's working memory, and it lives in the blackboard,
  not the context window.

## 5. Vulnerability research

Scoped to authorised targets: your own code, your own binaries, and eval fixtures.
An explicit `scope.yaml` in the project lists permitted targets; the VR agent's
tools refuse to operate outside it, and the morning report states the scope in
effect.

- **Source-level:** semgrep with local rulepacks (plus project-specific rules the VR
  agent may author — a rule with a proving test case is a legitimate artifact),
  bandit, clang-tidy security checks, and taint-style queries.
- **Binary/dynamic:** AFL++ / libFuzzer harness synthesis, ASAN/UBSAN/MSAN builds,
  crash triage and deduplication (stack hashing), minimisation (`afl-tmin`),
  `angr` for reachability questions.
- **The artifact discipline is the whole game here.** `VulnFinding` requires:
  ```
  VulnFinding:
    class: CWE-xxx
    location: file:line | binary+offset
    reachability: how untrusted input reaches it (path, with evidence)
    poc: { input_blob_sha, repro_script, expected_signal }   # REQUIRED
    sanitizer_trace_record_id: ...                            # REQUIRED
    impact: ...
    proposed_fix: patch ref
    fix_verification_record_id: ...   # PoC no longer triggers, tests still green
  ```
  No PoC and no sanitizer trace ⇒ not a finding, just a hypothesis. This kills the
  dominant failure mode of LLM security work: confident, unfalsifiable claims.
- **Fuzzing fits overnight runs perfectly** — it's CPU-bound, not LLM-bound, so it
  runs in the background while the model works on other stories. The scheduler
  should treat long-running fuzz campaigns as a separate resource class with their
  own budget, and triage crashes as they arrive.
- **Eval tasks:** Juliet/SARD subsets (ground truth included), planted CVE-class
  bugs reintroduced into pinned open-source snapshots, and "here is a parser, find
  the bug" tasks with a known answer. Score on true positives found, and — equally
  important — **false-positive rate**, which is where LLM security tooling usually
  falls apart.
- **Fix verification is part of the loop:** a VR finding that produces a fix must
  re-run the PoC (must no longer trigger) and the full test suite (must stay
  green), or it isn't done.

## 6. Cross-domain: CI

DevOps owns an offline CI definition that mirrors the gate battery exactly, so
"passes CI" and "passes the gates" cannot diverge:

```
stages: lint → types → unit → coverage → mutation → sanitizers →
        scan → build(from-scratch) → runtime-image → acceptance-demo → docs
```

Run it locally (`act`-style or a plain Makefile driver) since there's no network.
The CI config is generated from the same playbook the gates read — one source of
truth, no drift.
