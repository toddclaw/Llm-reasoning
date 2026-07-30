# 00 — Overview, Thesis, and Principles

## 1. The problem

You want to hand a scrum-team-shaped request to a set of local agents at 22:00 and
find, at 07:00, a finished increment: built, tested, mutation-tested, reviewed,
security-scanned, demonstrated in the target environment, documented, CI-green.

Two hard constraints shape everything:

1. **No internet, anywhere in the topology.** Weights live on an on-prem H200 rack;
   the agents, docs corpus, and eval fixtures live on an air-gapped laptop; the
   software under evaluation runs in isolated Proxmox VMs with no route back. See
   [05-inference-and-topology.md](05-inference-and-topology.md) for the full picture.
2. **Locally-hosted open models.** Qwen3.5-397B-A17B and Qwen3-Coder-Next (FP8).
   These are frontier-class, but the design principle is unchanged and still worth
   holding to: **reliability comes from what the harness can prove, not what the
   model claims.** A stronger model hallucinates less often — which is exactly the
   regime where a human stops checking and gets burned. The gates are what make the
   output trustworthy enough to accept unseen in the morning.

> **Note on the original thesis.** This plan began as a bet that a *small* local
> model plus a rigorous external System 2 could rival a frontier model. The
> hardware answer (A1) moved the target to frontier-class local models, so the
> System 2 scaffold is no longer compensating for a weak base — it is buying
> *trust*: verifiable, provenance-backed, unattended-overnight-safe output. The
> "smaller LLM" experiment is preserved as an eval axis (run the same suite with a
> small Qwen behind each class and measure the gap), because it's still the
> cleanest test of how much the scaffold is worth versus the weights.

And four failure modes you have already been burned by:

| # | Failure | Why small models do it |
| - | ------- | ---------------------- |
| F1 | Unit tests that are empty or vacuous (`assert True`, construct-and-drop) | The reward signal in the prompt is "produce a test file", not "produce a discriminating test" |
| F2 | Features that don't work in the target environment | Model reasons about an idealised environment it invented |
| F3 | Tests never actually run — results asserted, not observed | Producing a plausible transcript is cheaper than producing a real one |
| F4 | Tests that a human can't read | No pressure toward comprehension; naming and structure are unconstrained |

Every one of these is a **verification** problem, not a prompting problem. That
observation drives the architecture.

## 2. Thesis: System 2 belongs in the harness, not the weights

Kahneman's framing maps onto this cleanly, and it is more than a metaphor — it
tells you *where to spend engineering effort*.

**System 1 — what the small model natively is.** One forward pass. Fast,
associative, fluent, confident, and unable to notice its own errors. Excellent at:
"rewrite this function to use a dict", "name this variable", "given this stack
trace and this file, produce a patch". Terrible at: "hold nine constraints across
forty minutes of work".

**System 2 — what we build around it.** In humans, System 2 is slow, serial,
effortful, and *works by externalising state*. We reproduce its five mechanisms
explicitly:

| System 2 mechanism | Implementation in Nightshift |
| ------------------ | ---------------------------- |
| Deliberate decomposition | The workflow state machine + architect-driven story splitting. Every LLM call is one bounded decision. |
| Working memory held outside intuition | The blackboard: typed artifacts in SQLite + git, not a chat transcript. Context is *assembled* per call, never accumulated. |
| Checking intuition against evidence | The gate battery. Deterministic predicates over harness-produced evidence. |
| Search and backtracking | Best-of-N candidate patches scored by the gates; escalation ladder; ADR revisit. |
| Metacognition / knowing you don't know | Fresh-context critic agents, hallucination accounting, explicit `BLOCKED` with a human question. |

The corollary that governs the whole design:

> **Reliability comes from what the harness can prove, not from what the model can
> claim. Any question a deterministic check can answer must never be delegated to
> a model.**

This is why F1–F4 die: they are all "the model claimed something". A red-proof
gate, a mutation score, a container run, and an attested test record don't care
what the model claimed.

## 3. Design principles

**P1 — Bounded-context calls.** Every LLM invocation is one bounded decision with
only the context that decision needs — not because the model can't hold more (it
can; it's a 397B), but because decomposition is what makes each step *gateable* and
keeps the reviewer/verifier honest. The per-call context budget is a swept
parameter, not a fixed 8k ([05](05-inference-and-topology.md) §6); the discipline is
"one decision per call", not a token count. Context assembly is code, one function
per role, unit-tested like any other code.

**P2 — Agents are state handlers, not chatters.** No free-form agent-to-agent
conversation. Small models thrash in open loops: they agree with each other, drift,
and converge on "looks good to me". Handoffs are typed artifacts through the
blackboard; routing is a state machine written in Python. The Manager agent handles
*exceptions*, it does not do routing.

**P3 — Provenance or it didn't happen.** Every factual claim that a gate depends on
must trace to a `Record` written by the harness (test run, build, scan, container
exec). Model text that asserts an unbacked result is discarded and counted as a
hallucination event in the metrics.

**P4 — Structure is enforced at decode time.** All structured outputs are produced
under a grammar (llama.cpp GBNF / vLLM XGrammar). We never parse hopeful JSON out
of prose. This alone removes a large class of small-model failures.

**P5 — The environment is a contract, not an assumption.** A declarative
`TargetEnvironment` spec is built into an image once, offline. Builds, tests, and
demos happen *there*. "Works on my dev tree" is not a state the machine has.

**P6 — Tests before code, red proven before green.** TDD is not a style preference
here; the RED proof is our strongest anti-vacuity signal and it is free.

**P7 — The scaffold is configuration, so it can be evaluated.** Prompts,
decomposition depth, gate thresholds, retry ladders, model routing — all live in a
versioned `playbook.yaml`. A run is `(playbook_version × model_set × task_suite) →
scored results`. That makes "iterate on the reasoning structure until it performs
well" an engineering loop instead of a vibe.

**P8 — Never spin.** Bounded attempts, oscillation detection, and a hard escalation
ladder ending in `PARKED` with a crisp human question. An overnight run that parks
three stories and finishes five is a good night. An overnight run that burns nine
hours on one story is a bug in the harness.

**P9 — No agent framework.** The control flow *is* the product. LangChain/CrewAI/
AutoGen-style abstractions hide exactly the thing we are engineering. Direct calls
to an OpenAI-compatible endpoint, plus our own loop.

**P10 — Git is the substrate.** One branch per story, one commit per attempt, one
worktree per concurrently-active agent. Rollback is `git reset`, diffing attempts
is `git diff`, and the audit trail is free.

## 4. What "different agents with different models" actually buys

Three distinct things, worth separating because they have different costs:

1. **Context isolation** (free, huge). The TDD developer must not see the
   architect's deliberation; the reviewer must not see the implementer's rationale
   — a critic that has read the author's reasoning is a rubber stamp. Independent
   context is the single most valuable property of the multi-agent design.
2. **Prompt/role specialisation** (free). Different system prompts, tool
   allowlists, output schemas, sampling parameters.
3. **Different backend models** (expensive on a laptop). Only 1–2 models fit in
   memory at once. So roles are *routed* to a small resident set — see
   [05-inference-and-topology.md](05-inference-and-topology.md). Design the role
   registry so each role names a **model class** (`reasoner`, `coder`, `cheap`),
   and a routing table binds classes to concrete endpoints. That way the roster is
   independent of your hardware.

## 5. Honest expectations

- The local models are frontier-class, but open-ended *design* is still the weakest
  link — the harness gates adherence to a design, not the wisdom of it. Expect
  strong results on well-specified, gate-checkable increments (most of a backlog)
  and treat the Architect's output as the thing you personally review in the
  morning. Self-consistency partially mitigates it ([03](03-verification.md) §5).
- **The bottleneck is the laptop's compile/test throughput, not inference**
  ([05](05-inference-and-topology.md) §4). Expect single-digit stories per night at
  the start; the gates are expensive by design, and mutation testing plus best-of-N
  evaluation are the big spends. Phase the budget deliberately.
- The eval suite is not optional garnish. Without it you will tune prompts by
  anecdote and plateau. Build it in Phase 1, before most of the agents.
- Expect the first working version to be *slow and correct*, then optimise. The
  ordering matters: a fast unreliable overnight run is worse than nothing, because
  you'll trust it.

## 6. Glossary

| Term | Meaning |
| ---- | ------- |
| **Blackboard** | The durable shared state (SQLite + git worktree) holding all artifacts. |
| **Artifact** | A pydantic-validated, versioned, immutable output of an agent (Charter, Story, Contract, TestSuite, Patch, …). |
| **Record** | Harness-produced evidence (TestRunRecord, BuildRecord, ScanRecord, DemoRecord). Only the harness writes these. |
| **Gate** | A deterministic predicate over Artifacts + Records that guards a state transition. Has a stable ID (`G-RED-1`). |
| **Evidence Bundle** | The set of Records supporting a story reaching `ACCEPTED`. Shipped in the morning report. |
| **Playbook** | Versioned YAML config defining prompts, gates, thresholds, routing, ladders. The unit under evaluation. |
| **Target Environment** | Declarative spec of where the software must actually run; realised as an offline container/VM image. |
| **Ladder** | The bounded escalation sequence applied when a gate fails. |
