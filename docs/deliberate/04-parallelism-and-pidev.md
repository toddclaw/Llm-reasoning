# 04 — Parallelism and pi.dev

Your choice: **pi orchestrates *above* the layer.** Deliberate stays a stateless
per-call service; pi's parallelism runs on top of it.

## 0. What pi actually is (and why this fits perfectly)

[pi](https://pi.dev/) is a **coding-agent harness** — a terminal agent in the same
family as Claude Code — built around a deliberately thin agentic loop: *stream the
model's response → execute the tool calls it emits → append the results → repeat*. It
points at a model endpoint, and its parallelism comes from **orchestration
extensions** (pi-fleet, agent-pi, pi-orchestration, pi-extensible-workflows) that fan
out multiple pi agents concurrently, each isolated in its **own git worktree**.

Two facts make the integration clean and confirm the earlier design:

1. **pi talks to a model endpoint, so Deliberate slots in with a `base_url` change.**
   Point pi at Deliberate instead of at vLLM directly and every pi agent transparently
   gets the reasoning + Qwen adaptation. This is the entire payoff of choosing an
   OpenAI-compatible surface, and it is *exactly* your "Claude Code underperforms with
   Qwen" pain, since pi is the Claude-Code-shaped tool you'd use with Qwen.
2. **pi's orchestration extensions are the Level-1 parallelism** in the diagram
   below — N pi agents in N worktrees, each an independent client of Deliberate.
   Deliberate doesn't orchestrate anything; it just has to be safe to call
   concurrently, which §2 guarantees.

## 1. Two levels of parallelism, one shared bottleneck

```
        pi orchestration extension  (pi-fleet / pi-orchestration / workflows)
        ┌───────────┬───────────┬───────────┬───────────┐
    pi agent1   pi agent2   pi agent3   pi agent4    …   (parallel, own worktrees)
        │           │           │           │
        ▼           ▼           ▼           ▼
   ┌─────────── DELIBERATE replicas (stateless, load-balanced) ───────────┐
   │  each request may itself fan out:  best_of_n ×N,  parallel verifiers  │
   └───────────────────────────────┬──────────────────────────────────────┘
                                    ▼
                    ADMISSION CONTROLLER  (shared)
                                    ▼
                         vLLM  (Qwen3.5 on the rack)
```

- **Level 1 — pi × agents:** many independent pi agents (one per worktree) at once.
- **Level 2 — intra-request:** a single deliberation fans out (N candidates,
  parallel bias-probes, parallel verifiers).

Both levels ultimately hit **one shared vLLM**. So the thing that actually needs
engineering is not parallelism (both levels are easy) but **fair, bounded
multiplexing onto the rack**. That's §3.

## 2. What "stateless & scalable" requires of Deliberate

To make Level 1 free for pi.dev:

- **No cross-request state** in the default path ([01](01-architecture.md) §4).
  Replicas are interchangeable; pi.dev needs no session affinity.
- **Horizontal replicas.** Run K Deliberate processes behind a balancer (or as K
  pods). Because each is stateless, K is a throughput dial with no coordination.
- **Idempotent under seed.** Retries and speculative duplicate calls (which parallel
  orchestrators love) are safe.
- **Per-call isolation.** One agent's tools, corpus, scope, and effort are carried in
  its request; nothing leaks between concurrent callers.
- **Bounded work per request.** Every request has a hard token/wall/model-call budget
  so a single pathological task can't starve the pool.

## 3. Admission control — the one hard part

50 pi.dev agents, each possibly doing best-of-8, is 400 concurrent generations aimed
at one endpoint. Without control this thrashes the rack's KV cache and tail latency
explodes. Deliberate therefore owns a **shared admission controller** in front of the
backend client:

- **Global concurrency cap** to vLLM (`server.max_concurrent_requests`), sized to the
  rack's healthy continuous-batch width — past that point more in-flight sequences
  only hurt.
- **Fair queueing across callers.** A `caller_id`/`session_id` (or pi.dev task id)
  gets a fair share, so one fan-out-heavy agent can't monopolise the rack. Weighted
  fair queuing, weights configurable.
- **Priority classes.** Interactive/low-effort calls jump ahead of big background
  best-of-N batches, so a human-facing agent stays responsive while a deep
  deliberation runs behind it.
- **Backpressure, not failure.** At capacity, callers queue (with a max wait) rather
  than erroring; the effort gate is how latency-sensitive callers opt down.
- **Speculative-cancel.** If best-of-N already has enough passing candidates, cancel
  the stragglers to return their slots — cheap given continuous batching.

If Deliberate runs as multiple replicas, the controller is either a shared service
(a small broker the replicas coordinate through) or, simpler, each replica caps
itself and the rack's own scheduler absorbs the rest. Start with per-replica caps;
add a shared broker only if measurement shows unfairness. Don't build the broker on
spec.

## 4. Binding to pi

**Primary: as pi's model provider.** Configure pi's model endpoint as Deliberate's
`base_url`. Zero custom code — pi thinks it's talking to a model and gets a reasoning
service instead. Every pi agent, and every agent an orchestration extension spawns,
inherits it. This is the whole payoff of the OpenAI-compatible choice.

Optional niceties, only if pi exposes the hooks:
- **Task/priority propagation.** If pi (or pi-fleet) sets a request header with its
  task/worktree id, Deliberate feeds it to the admission controller (§3) so pi's
  scheduling intent reaches the rack. Falls back to per-request fairness if absent.
- **Effort per agent.** An orchestration extension can set `reasoning_effort` (or the
  `qwen3.5:high` model-suffix) per agent role — a planner agent at `high`, a
  bulk-edit agent at `low` — without Deliberate needing to know pi's roster.

The **agent logic (the tool loop, worktrees, orchestration) stays in pi; the
reasoning stays in Deliberate.** Neither knows the other's internals.

## 5. The single-turn boundary — the one thing to get right

pi's loop *executes tools itself*: it takes the assistant turn, runs whatever tool
calls it contains, appends results, and calls the model again. Deliberate improves
**one assistant turn at a time**; it does **not** own pi's agentic loop and must never
try to execute pi's tools. This has concrete consequences:

- **A Deliberate request = one turn.** Given the conversation + pi's tool defs,
  Deliberate returns either a final message or `tool_calls`, in the OpenAI shape pi
  expects. All internal reasoning (frame, best-of-N, reflect) happens *while
  producing that single turn* and is invisible to pi.
- **Two ways the `frame` stage fills a knowledge gap** ([02](02-reasoning-modules.md)
  §2.1), and the distinction matters here:
  - *Deliberate's own tools* (its RAG/retrieval, configured server-side) run
    **inside** one turn — pi never sees them.
  - *pi's tools* (read a file, run a test) can only be executed by pi. So when
    framing decides it needs one, Deliberate **returns that tool call to pi**; pi runs
    it and calls back; on the next turn Deliberate continues reasoning with the
    result. Deliberate never reaches around pi to run the client's tools.
- **Effort applies per turn.** A high-effort deliberation on a turn that ends in a
  tool call still just returns the tool call — the effort bought a *better-chosen*
  tool call, not a bypass of pi's loop.
- **Statelessness is preserved** because pi carries the conversation between turns;
  Deliberate reconstructs its reasoning state from the messages each turn. Any
  cross-turn scratch Deliberate wants (e.g. a persisted Framing Brief) uses the
  optional `session_id` store ([01](01-architecture.md) §4), keyed by pi's
  worktree/task id.

Getting this boundary right is what keeps the two systems cleanly composable — and
it's the subtle bug to avoid: a reasoning layer that tries to run the harness's tools
will fight pi's loop instead of enriching it.

## 6. Observability across parallel runs

- Every request carries/gets a `trace_id`; pi's task/worktree id is propagated into
  the trace so you can reconstruct "which agent, which deliberation, which model
  calls" across a whole parallel run.
- Aggregate metrics (queue depth, rack utilisation, per-caller share, effort mix,
  tokens/task) are exported so you can see whether the pi fleet is saturating or
  starving the rack and tune replica count / caps accordingly.

## 7. Failure isolation

A parallel fleet needs one agent's failure to stay local:

- A stage crash or budget-exhaustion degrades that **one** request to "best answer so
  far" + an explicit trace note; it never takes down the replica.
- Backend hiccups (a vLLM restart) are retried within a request's budget, then
  surfaced as a normal error to that one caller — the other pi agents are unaffected.
- The admission controller sheds load (queues/deprioritises) rather than cascading a
  failure across callers.
