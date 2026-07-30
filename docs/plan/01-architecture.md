# 01 — Architecture

## 1. Component map

```
┌──────────────────────────────────────────────────────────────────────┐
│ CLI  (nightshift run | status | report | eval | replay)              │
└───────────────┬──────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────┐
│ ORCHESTRATOR                                                          │
│  • story state machine        • scheduler (worktree pool)             │
│  • escalation ladder          • budget accountant                     │
│  • deadlock / oscillation detectors                                   │
└───┬──────────────┬───────────────┬───────────────┬───────────────────┘
    │              │               │               │
┌───▼────────┐ ┌───▼──────────┐ ┌──▼───────────┐ ┌─▼──────────────────┐
│ BLACKBOARD │ │ AGENT RUNTIME│ │ GATE ENGINE  │ │ EVIDENCE STORE     │
│ SQLite+git │ │ ctx assembly │ │ G-* preds    │ │ Records, logs,     │
│ artifacts  │ │ grammar dec. │ │ thresholds   │ │ casts, artifacts   │
└────────────┘ └───┬──────────┘ └──┬───────────┘ └────────────────────┘
                   │               │
             ┌─────▼─────┐   ┌─────▼──────────────────────────────────┐
             │ MODEL     │   │ EXECUTION SANDBOX                      │
             │ ROUTER    │   │ target-env container, no network,      │
             │ llama-swap│   │ build/test/scan/demo runners           │
             └───────────┘   └────────────────────────────────────────┘
                   │
             ┌─────▼───────────────────────────────────────────────────┐
             │ TOOL LAYER  (LSP, repo search, docs RE trieval, shell)   │
             └─────────────────────────────────────────────────────────┘
```

Separately, sharing everything below the CLI:

```
┌──────────────────────────────────────────────────────────────────────┐
│ EVAL HARNESS  tasks/ + hidden oracles → scorer → results.db → report │
└──────────────────────────────────────────────────────────────────────┘
```

## 2. Data model

Two stores, deliberately:

- **SQLite (WAL)** — control plane. Stories, states, attempts, artifacts (as JSON),
  records, budgets, events. Crash-resumable; this is what makes overnight runs
  survivable.
- **Git** — data plane. Source, tests, docs. One branch per story
  (`ns/story/<id>`), one commit per attempt with a structured trailer
  (`Nightshift-Attempt: 3`, `Nightshift-Agent: tdd-dev`, `Nightshift-Gate: G-GREEN-1`).

Large blobs (logs, coverage XML, asciinema casts, core dumps) go to
`.nightshift/evidence/<record_id>/` on disk, referenced by hash from SQLite.

### 2.1 Core tables

```
project(id, name, repo_path, target_env_id, playbook_version)
epic(id, project_id, title, charter_json)
story(id, epic_id, key, title, state, priority, blocked_reason, budget_json)
artifact(id, story_id, kind, version, author_role, schema_version, body_json,
         created_at, supersedes_id)
record(id, story_id, kind, tree_sha, cmd, cmd_sha, exit_code, stdout_sha,
       stderr_sha, duration_ms, env_id, blob_dir, created_at, attestation)
gate_result(id, story_id, gate_id, attempt, passed, detail_json, record_ids)
attempt(id, story_id, n, from_state, to_state, agent_role, model_id,
        prompt_tokens, completion_tokens, wall_ms, outcome)
event(id, story_id, ts, kind, payload_json)          -- append-only audit log
budget(scope, key, tokens_used, wall_ms_used, limit_json)
```

`record.attestation` is an HMAC over `(tree_sha, cmd_sha, exit_code, stdout_sha)`
keyed by a per-run secret held only by the harness. Not security against an
attacker — it is a *type system for provenance*, making it structurally impossible
for an agent-authored artifact to masquerade as observed evidence.

### 2.2 Artifact kinds

All are pydantic v2 models, versioned with `schema_version`, immutable, and
superseded rather than mutated.

| Kind | Author | Key fields |
| ---- | ------ | ---------- |
| `Charter` | Product Owner | problem, users, success measures, out-of-scope, constraints |
| `Story` | Product Owner | key, narrative, `acceptance: [AcceptanceCriterion]`, INVEST self-check |
| `AcceptanceCriterion` | PO | id, given/when/then, `executable_ref` (path::test_name), observable |
| `ArchDecision` (ADR) | Architect | context, options considered, decision, consequences, revisit-triggers |
| `Contract` | Architect | module layout, public signatures, invariants, error taxonomy, data schemas |
| `TestPlan` | TDD Dev | per-criterion test intents, boundary/negative/property cases, fixtures |
| `TestSuite` | TDD Dev | files written; each test maps to ≥1 criterion id |
| `Patch` | TDD Dev | git diff ref (commit sha), rationale, touched symbols |
| `ReviewVerdict` | Reviewer / DevSecOps / UX | scorecard, findings[severity, file:line, rule, fix-hint], verdict |
| `RunbookDoc` | DevOps | build/run/deploy steps, all executable |
| `UserDoc` | UX + Dev | README/CLI help/error-message copy |
| `ReleaseNote` | Manager | what changed, evidence bundle index |
| `BlockedQuestion` | any | the single crisp question a human must answer |

### 2.3 Record kinds

| Kind | Produced by | Contains |
| ---- | ----------- | -------- |
| `BuildRecord` | build runner in target env | compiler output, warnings-as-errors status, artifact hashes |
| `TestRunRecord` | test runner | cmd, exit, per-test results (parsed junit-xml), duration |
| `RedProofRecord` | test runner on pre-patch tree | which tests failed and *with what message* |
| `CoverageRecord` | coverage tool | line/branch coverage, diff-coverage on changed lines |
| `MutationRecord` | mutmut / mull | mutants generated, killed, survivors with locations |
| `LintRecord` | ruff/clang-tidy/shellcheck/mypy | findings |
| `ScanRecord` | semgrep/bandit/gitleaks/ASAN | findings with severity |
| `DemoRecord` | acceptance runner | asciinema cast, exit codes, stdout, screenshots |
| `SymbolRecord` | pyright/clangd | every referenced external symbol + resolution status |
| `ComprehensionRecord` | probe model | restatement of a test's behaviour + similarity score |

## 3. The story state machine

```
                    ┌────────────┐
   request  ───────▶│   INTAKE   │
                    └─────┬──────┘
                          │ PO shapes
                    ┌─────▼──────┐   G-SHAPE-*
                    │   SHAPED   │────────────────┐
                    └─────┬──────┘                │
                          │ Architect              │
                    ┌─────▼──────────┐ G-ARCH-*    │
                    │  ARCHITECTED   │─────────────┤
                    └─────┬──────────┘             │
                          │ PO+Dev bind criteria    │
                    ┌─────▼──────────┐ G-CONTRACT-*│
                    │   CONTRACTED   │─────────────┤
                    └─────┬──────────┘             │
                          │ TDD Dev writes tests    │
                    ┌─────▼──────┐   G-RED-*       │
                    │    RED     │─────────────────┤   any gate failure
                    └─────┬──────┘                 │        │
                          │ TDD Dev implements      │        ▼
                    ┌─────▼──────┐   G-GREEN-*     │  ┌───────────┐
                    │   GREEN    │─────────────────┤  │  LADDER   │
                    └─────┬──────┘                 │  │ retry →   │
                          │ refactor under green    │  │ escalate →│
                    ┌─────▼──────────┐ G-REFACTOR-*│  │ decompose→│
                    │   REFACTORED   │─────────────┤  │ revisit → │
                    └─────┬──────────┘             │  │ park      │
                          │ Reviewer + DevSecOps    │  └─────┬─────┘
                    ┌─────▼──────┐   G-REVIEW-*    │        │
                    │  REVIEWED  │─────────────────┤        ▼
                    └─────┬──────┘                 │  ┌───────────┐
                          │ DevOps: CI in target env│  │  PARKED   │
                    ┌─────▼──────────┐ G-INTEGRATE-*│  │ (+question)│
                    │   INTEGRATED   │─────────────┤  └───────────┘
                    └─────┬──────────┘             │
                          │ acceptance runner       │
                    ┌─────▼────────────┐ G-DEMO-*  │
                    │  DEMONSTRATED    │───────────┤
                    └─────┬────────────┘           │
                          │ UX + Dev docs           │
                    ┌─────▼──────────┐ G-DOC-*     │
                    │   DOCUMENTED   │─────────────┘
                    └─────┬──────────┘
                          │ PO signs off vs criteria
                    ┌─────▼──────┐
                    │  ACCEPTED  │──▶ merged to integration branch
                    └────────────┘
```

Rules:

- Transitions are executed by code. An agent's output can only *propose* a
  transition; the gate decides.
- A gate failure never advances the state. It increments `attempt` and invokes the
  ladder (see [07-overnight-autonomy.md](07-overnight-autonomy.md)).
- `REFACTORED` re-runs the full `GREEN` battery. Refactoring that changes behaviour
  is a rejected patch, not a discussion.
- `REVIEWED` failures with severity ≥ `major` bounce to `GREEN`, not to `RED` —
  the tests were already proven, don't churn them.
- Any state may transition to `PARKED`. Nothing transitions out of `PARKED` without
  a human answer.

## 4. Concurrency model

- The orchestrator maintains a pool of **git worktrees** (`.nightshift/wt/<n>`),
  one per concurrently-running story. This gives real filesystem isolation without
  cloning.
- Concurrency is bounded by **inference capacity**, not CPU. With one resident
  model, LLM calls serialise through the router's queue; the parallelism win comes
  from overlapping model calls with the *expensive non-model work* (compiles,
  mutation runs, fuzzing).
- Therefore: schedule so that at most one story is in an LLM-bound state while
  others sit in gate-bound states. The scheduler is a simple priority queue with a
  `resource_class` per state (`llm` vs `cpu`).
- Stories touching overlapping files (per the Architect's `Contract.module_layout`)
  are serialised by a file-level lock table to avoid merge hell. The Architect is
  responsible for splitting into non-overlapping stories where possible; the
  Manager escalates when it can't.

## 5. Tool layer

Agents get a small, precise toolset. Precision matters more than breadth for small
models — every tool must have a narrow signature and a grammar-constrained call
format.

| Tool | Backing | Why |
| ---- | ------- | --- |
| `read_span(path, start, end)` | fs | Never dump whole files; force spans |
| `search(pattern, glob)` | ripgrep | Bounded, capped result count |
| `symbol_def(name)` / `symbol_refs(name)` / `hover(path,line,col)` | **LSP** (pyright, clangd, bash-language-server) | Kills API hallucination; gives *typed* context instead of guessed context |
| `diagnostics(path)` | LSP | Model sees the compiler's opinion before the harness does |
| `docs_search(query, corpus)` | local embedding + BM25 index over cppreference, Python docs, man pages, project headers | Offline grounding; small models hallucinate APIs badly |
| `apply_patch(diff)` | git apply | Only mutation path into the tree |
| `run(cmd)` | sandbox | **Restricted**: only allowlisted commands, and its output becomes a Record |
| `note(key, value)` | blackboard | Scratch memory that persists across the story's attempts |

Notes:

- The LSP-backed tools are the highest-leverage item on this list. `clangd` and
  `pyright` turn "does this symbol exist and what is its type" from a model guess
  into a fact. Build them in Phase 1.
- `run` is not a general shell. Each role has an allowlist; anything else requires
  the DevOps agent, which has a wider (still-allowlisted) set.
- Every tool result is truncated to a per-tool token budget with an explicit
  `[truncated: N more lines, refine your query]` marker. Silent truncation is how
  small models get confidently wrong.

## 6. Agent runtime

One call = one function:

```python
def invoke(role: Role, story: Story, state: State, attempt: int) -> Artifact:
    ctx     = ROLE_REGISTRY[role].assemble_context(story, state, attempt)  # code
    prompt  = render(ROLE_REGISTRY[role].template, ctx)                    # jinja
    grammar = grammar_for(ROLE_REGISTRY[role].output_schema)               # GBNF
    raw     = router.complete(
                  model_class=ROLE_REGISTRY[role].model_class,
                  prompt=prompt, grammar=grammar,
                  sampling=ROLE_REGISTRY[role].sampling)
    art     = ROLE_REGISTRY[role].output_schema.model_validate_json(raw)
    art     = strip_unbacked_claims(art)          # P3 enforcement
    blackboard.put(art)
    return art
```

`strip_unbacked_claims` walks the artifact for any field typed as a result claim
(`tests_pass`, `build_ok`, `coverage_pct`, …) and either replaces it with the value
from the corresponding Record or, if no Record exists, nulls it and emits a
`hallucinated_claim` event. Agents learn nothing from this; the *metrics* do, and
the eval harness uses hallucination rate as a first-class score.

**Prompt layout is fixed for cache reuse** (see
[05-model-serving-offline.md](05-model-serving-offline.md)): stable prefix
(role system prompt → tool definitions → contract → domain playbook) then volatile
suffix (current failure evidence → the ask). This ordering gives large prompt-cache
hit rates across the retry ladder, which is where most of the tokens go.

## 7. Tech stack

| Concern | Choice | Rationale |
| ------- | ------ | --------- |
| Language | Python 3.12 | Tooling ecosystem for test/coverage/mutation/LSP |
| Packaging | `uv` with a vendored wheel cache | Fast, and works fully offline |
| Schemas | pydantic v2 | Validation + JSON Schema → GBNF grammar generation |
| Store | SQLite (WAL) + plain SQL via `sqlite3` | Zero ops, crash-safe, inspectable at 3am |
| CLI | `typer` | — |
| Logging | `structlog` → JSONL | Trajectory logs are eval input, so they must be structured |
| Templates | Jinja2 with `StrictUndefined` | A missing context var must crash, not silently render empty |
| Sandbox | Podman/Docker rootless, `--network=none` | Target env realism + containment for RE work |
| Inference | llama.cpp `llama-server` behind `llama-swap` | OpenAI-compatible, GGUF, hot-swap, laptop-friendly |
| **Not used** | LangChain, CrewAI, AutoGen, LlamaIndex | They abstract away the control flow that *is* the product |

A thin `LLMProvider` interface with `local` (llama.cpp) and `anthropic`
implementations. Runtime default is local and offline; the Anthropic path exists
only for (a) bootstrapping fixtures during development and (b) computing a
frontier-model ceiling on the eval suite so you know how much headroom the scaffold
still has. It must be impossible to enable accidentally: guarded by an explicit
`--allow-network` flag that also flips a loud banner.

## 8. Repository layout

```
nightshift/
  orchestrator/    state machine, scheduler, ladder, budgets, detectors
  blackboard/      sqlite schema, repositories, artifact models
  agents/          role registry, context assemblers, prompt templates
  gates/           one module per gate family; pure predicates over evidence
  runners/         build, test, coverage, mutation, lint, scan, demo, fuzz
  sandbox/         image build, exec, resource limits, seccomp profiles
  models/          router, llama-swap config, grammar generation, cache policy
  tools/           lsp, search, docs index, patch, restricted run
  domains/         python/, cpp/, bash/, reverse_eng/, vuln_research/
  eval/            task loader, oracle runner, scorer, sweeper, reporting
  report/          morning report generation
playbooks/         default.yaml, experiments/*.yaml
tasks/             eval task suite (public part)
tasks_oracles/     hidden oracles — never mounted into an agent sandbox
docs/
```

## 9. Key architectural decisions to record as ADRs on day one

1. Deterministic state machine over free-form agent conversation.
2. Provenance-typed evidence; agents cannot assert results.
3. Grammar-constrained decoding for all structured output.
4. Git worktrees as the isolation primitive.
5. Playbook-as-config so the scaffold is the unit under evaluation.
6. LSP as the primary code-navigation tool rather than grep-only.
7. No third-party agent framework.
