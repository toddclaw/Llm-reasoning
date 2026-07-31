# 10 — Two Work Paths and Existing-Codebase Support

Added after A5 and A6. Two decisions reshape the system:

1. **Almost all work is on existing codebases**, not greenfield.
2. **There are two distinct-but-related paths of work**, chosen per session.

## 1. The two paths

You described them precisely, so the design mirrors them rather than forcing both
through the scrum roster:

| | **BUILD path** | **INVESTIGATE path** (RE/VR) |
| --- | --- | --- |
| Goal | produce working, tested, documented software | answer questions about a system under evaluation |
| Central artifact | `Patch` (code) | `Finding` (a claim + its evidence) |
| Definition of done | criteria demonstrated in target env, gates green | every conclusion traced to reproducible data |
| Failure to avoid | code that doesn't work / vacuous tests | a confident claim that isn't backed by data |
| Roster | PO, Architect, TDD Dev, Reviewer, DevOps, DevSecOps, UX, Manager | Analyst, Verifier, Reporter, Manager |
| Language | Python now → C/C++ later | C / C++ targets |

They share **the entire substrate**: blackboard, state machine engine, gate engine,
provenance/attestation, model router, tool layer, sandbox, eval harness, morning
report. The two paths are different *state machines and rosters* over one harness —
not two systems. This is why P3 (provenance or it didn't happen) was worth making
the spine: it's the same principle in both paths, just applied to code evidence
versus analysis evidence.

### Selecting the path

Yes — set it at session start, both ways you asked about:

```bash
nightshift run  --path build       --project ./mytool     --backlog ./stories.yaml
nightshift run  --path investigate --target te-vm-03 --questions ./questions.yaml
```

Equivalent subcommand forms are fine and may read better; pick one and keep it:

```bash
nightshift build    --project ./mytool      --backlog ./stories.yaml
nightshift analyze  --target te-vm-03 --questions ./questions.yaml
```

- The path selection (flag or subcommand) picks the state machine, the roster, the
  default gate battery, and the artifact schemas. It is recorded in the run row and
  printed in the report.
- It is also exposed through the config file (`path: build|investigate`) so a
  wrapper script or a future UI sets it without CLI flags.
- A single project may have runs of both kinds over its life (build a tool, then
  investigate with it). They share the blackboard, so a `Finding` from an
  investigate run **auto-seeds a BUILD story** — see §1a.

## 1a. Cross-path auto-seeding (A20)

When an INVESTIGATE run produces a verified `Finding` with build implications ("the
target parses length-prefixed frames with no bounds check at offset X"), the system
**automatically creates a BUILD story** from it rather than waiting for you to bridge
the two paths by hand. The mechanics keep this safe:

- The seeded story enters the BUILD backlog at `INTAKE` as a normal story, carrying a
  `derived_from: <finding_id>` provenance link. It is **not** silently implemented —
  it flows through the full state machine (PO shaping, Architect, gates) like any
  other story.
- It is created **proposed/enabled by default** but flagged in the morning report's
  "seeded from findings" section, so under the review-and-answer operating model
  (A10) you see every auto-seeded story and can deprioritise or kill it before the
  next night's run.
- The `Finding`'s evidence (the reproduction script, the sanitizer trace) is attached
  to the story, so the TDD Dev starts with a *failing test derived from the PoC* —
  the cleanest possible RED for a "build a tool / fix that handles X" story.
- Only **verified** findings (reproduced by the Verifier, §2) can seed a story. An
  unverified hypothesis cannot spawn build work — the same provenance gate as
  everywhere else, so auto-seeding never launders a guess into a task.

This is the workflow you described: "I learned X about the target, now build a tool
that interacts with / hardens against X", made automatic without losing the audit
trail or your morning veto.

## 2. The INVESTIGATE path state machine

The provenance discipline that makes BUILD trustworthy maps directly onto
analysis. A question flows:

```
POSED ──▶ SCOPED ──▶ PLANNED ──▶ COLLECTED ──▶ ANALYZED ──▶ VERIFIED ──▶ REPORTED ──▶ ANSWERED
```

| State | Handler | Produces | Gate (representative) |
| ----- | ------- | -------- | --------------------- |
| POSED | human | `Question` (what we want to know, what would count as an answer) | question has a stated acceptance-of-answer condition |
| SCOPED | Analyst | `Scope` (which VMs / addresses / binaries are in bounds) | scope ⊆ authorised `scope.yaml`; nothing out of bounds |
| PLANNED | Analyst | `InvestigationPlan` (steps, each producing a named datum) | every step names the evidence it will yield |
| COLLECTED | harness runner | `Evidence` records (tool output, traces, dumps) — **attested** | each datum attested, tree/target-bound |
| ANALYZED | Analyst | `Finding[]` (claim + cited evidence + reasoning) | every claim cites ≥1 attested Evidence id |
| VERIFIED | Verifier (fresh context) | `Verification` (independently reproduces each claim) | **reproduction script re-run by harness matches the claim** |
| REPORTED | Reporter | `AnalysisReport` | no sentence without a backing Evidence/Verification id |
| ANSWERED | human/Manager | maps the original Question to the Findings | question's acceptance condition met |

The load-bearing states are **COLLECTED** and **VERIFIED**:

- **COLLECTED** — the Analyst never eyeballs a binary and asserts. It emits a *script*
  (Ghidra headless, r2pipe, angr, a parser) that the harness runs; the script's
  output is the attested Evidence. This is the RE/VR incarnation of "agents cannot
  report results, only runners produce records". A claim with no script that
  produces it is not admissible.
- **VERIFIED** — a second agent with **fresh context and no sight of the Analyst's
  reasoning** takes each `Finding`, regenerates a reproduction, and the *harness*
  re-runs it. A claim that doesn't reproduce is demoted to a hypothesis and bounced
  back to ANALYZED. This is the direct analogue of the independent Reviewer, and it
  is what satisfies your A6 requirement — "all conclusions backed by data,
  verifiable from the data provided."

### INVESTIGATE artifacts

```
Question:        text, why_it_matters, answer_acceptance (what evidence would settle it)
Scope:           allowed_cidrs[], vms[], binaries[], explicitly_out_of_bounds[]
InvestigationPlan: steps[{intent, method, produces_datum}]
Evidence:        record_id, method, cmd, target, output_sha, attestation   # harness-written
Finding:         claim, confidence, cites:[evidence_id], reasoning, reproduction_script_ref
Verification:    finding_id, reproduced:bool, matched:bool, verifier_record_id
AnalysisReport:  narrative, findings[], evidence_index, scope_statement, unknowns[]
```

`Finding.confidence` is not the model's vibe — it is a function of how many
independent Evidence records corroborate it and whether Verification reproduced it.
Computed by code from the evidence graph, not asserted by the Analyst.

### Scope enforcement (A19)

Scope is defined by a **local-only network range**, which matches how the targets are
addressed. The remote-runner broker refuses any `run_in_target` whose destination
falls outside the allowed CIDRs, and refuses any destination that isn't
RFC-1918/local — a belt-and-braces guard against an analysis script trying to reach
off-network:

```yaml
# scope.yaml
allowed_cidrs: [ 10.20.0.0/24 ]     # the target VMs' local segment
require_local_only: true            # reject anything outside RFC-1918 / link-local
vms:      [ te-vm-03, te-vm-04 ]    # optional allowlist by VM id, within the CIDRs
binaries: [ "sha256:…" ]            # optional: pin which samples are in-bounds
explicitly_out_of_bounds: [ 10.20.0.1 ]   # e.g. the gateway
```

Enforcement is in the broker (host tier), not in the agent, so a compromised or
confused agent cannot widen its own scope — the same principle as the agent
container's egress allowlist.

### INVESTIGATE gates (F1–F4 analogues)

Your four build failure modes have direct analysis-side twins, gated the same way:

| Build failure | Investigate twin | Gate |
| ------------- | ---------------- | ---- |
| Vacuous test | Ungrounded claim ("it looks like RC4") | Every claim cites attested evidence; uncited claim stripped |
| Doesn't work in target env | Analysis of the wrong build/version | Evidence bound to a specific target VM snapshot + binary hash |
| Test never run | Reasoning presented as if it were observed | Only harness-run scripts produce Evidence; model narration can't |
| Unreadable test | Report a human can't follow to the data | Reporter gate: every sentence links to evidence; a reader can trace each conclusion |

The "unknowns" list is mandatory and first-class — the honest analog of a parked
story. An investigation that states precisely what it could *not* determine, and
what data would settle it, is worth far more than one that overclaims. This is the
morning-report "parked questions" section for the INVESTIGATE path.

## 3. Existing-codebase support (BUILD path)

Almost all BUILD work extends existing repos, so a comprehension step precedes
`SHAPED`. New first state and a new role:

```
INTAKE ──▶ MAPPED ──▶ SHAPED ──▶ ARCHITECTED ──▶ ... (unchanged) ... ──▶ ACCEPTED
             ▲
       Codebase Cartographer
```

### Codebase Cartographer (`cartographer`)

- **Model class:** REASONER, large context. **Runs once per repo**, cached and
  incrementally refreshed on change (invalidate by file hash), not once per story.
- **Produces `CodebaseMap`:**
  ```
  CodebaseMap:
    modules[]:        path, responsibility (inferred), public_surface
    conventions:      naming, test_framework, error_handling_style, layout_rules
    build_system:     how it builds, how it tests, entry points
    dependency_graph: internal import/call edges; external deps + versions
    hotspots:         high-churn / high-complexity / low-coverage areas
    exemplars:        pointers to 2-3 model files, 2-3 model tests (for style transfer)
    invariants:       cross-cutting rules discovered (e.g. "all IO goes through io/")
    danger_zones:     code with no tests, generated code, vendored code — touch-carefully
  ```
- **Digest** of this map goes into the stable prompt prefix for every subsequent
  agent ([05](05-inference-and-topology.md) §5), so every agent inherits repo
  awareness at near-zero marginal cost thanks to prefix caching.
- **Conventions are inferred, then enforced.** The Cartographer's `conventions` feed
  the domain playbook's readability/style gates *for this repo* — so "match the
  existing code" becomes a checkable gate, not a hope. The `exemplars` feed the
  context assemblers ([02](02-agents.md) §4 rule 3): small and large models alike
  imitate a real in-repo example far better than they follow a style rule.

### Blast-radius control

Existing repos punish careless edits. Two mechanical guards:

- **G-ARCH-2 extended:** the Architect's `Contract` must list every file the story
  may touch, and the file-lock table + a hard write-scope in the worktree *enforce*
  it — an agent physically cannot write outside the declared blast radius.
- **`danger_zones` are read-only by default.** Touching vendored/generated/untested
  code requires an explicit `ScopeExpansion` artifact with rationale, surfaced to
  you in the morning report rather than done silently.
- **Characterization tests before change.** For a `danger_zone` with no coverage that
  a story must modify, the TDD Dev first writes *characterization tests* pinning
  current behaviour (a distinct `CHARACTERIZE` sub-step before `RED`), so a
  refactor's "don't change behaviour" gate has something to check against. This is
  the Michael-Feathers legacy-code discipline, made mechanical.

## 4. Language transition Python → C/C++

You'll start BUILD in Python and move tools to C/C++; RE targets are C/C++ from the
start. Implication for sequencing: the C++ **domain playbook and RE tooling in
[06](06-domain-playbooks.md) are needed earlier than the original Phase 4/5 ordering
assumed**, because the INVESTIGATE path needs C/C++ analysis tooling as soon as
INVESTIGATE exists. The roadmap in [08](08-roadmap.md) is revised to reflect this:
Python BUILD proves the thesis (Phases 0–3), then C/C++ analysis tooling and the
INVESTIGATE path land together (new Phase 4), with C/C++ *forward* development
following.
