# 04 — Parallelism and pi.dev

Your choice: **pi.dev orchestrates *above* the layer.** pi.dev runs many agents in
parallel; each agent is an ordinary OpenAI client pointed at Deliberate; Deliberate
stays a stateless per-call service. This is the cleanest split — top-level
parallelism is pi.dev's job, and the layer just has to be safe to call concurrently.

> **Honest note on pi.dev:** I've designed to a *general* contract for a parallel
> agent orchestrator rather than to pi.dev's specific API, which I don't want to
> assume. Everything below is framed as requirements Deliberate must meet for **any**
> such orchestrator; where pi.dev has specific hooks (a native provider interface, a
> results bus, its own concurrency primitives) we bind to them in a thin adapter.
> Q1 in [05](05-eval-and-roadmap.md) §7 captures what I need to confirm.

## 1. Two levels of parallelism, one shared bottleneck

```
                 pi.dev  (top-level orchestration)
        ┌───────────┬───────────┬───────────┬───────────┐
      agent1      agent2      agent3      agent4     …  (parallel, independent)
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

- **Level 1 — pi.dev × agents:** many independent tasks at once.
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

## 4. Binding to pi.dev specifically

Two integration shapes, depending on what pi.dev expects (Q1):

1. **As a model provider (most likely, and best).** pi.dev is configured with
   Deliberate's `base_url` as its OpenAI-compatible endpoint. Zero custom code —
   pi.dev thinks it's talking to a model; it gets a reasoning service. This is the
   whole payoff of the OpenAI-compatible choice.
2. **As a native component.** If pi.dev has its own provider/tool interface, ship a
   thin `deliberate-pidev` adapter that maps pi.dev's call convention onto
   Deliberate's HTTP API and forwards pi.dev's task/priority metadata into the
   admission controller (so pi.dev's scheduling intent reaches the rack). This is a
   small package precisely because the core stays protocol-clean.

Either way, the **agent logic lives in pi.dev; the reasoning lives in Deliberate.**
They compose without either knowing the other's internals — which is exactly the
modularity you asked for.

## 5. Observability across parallel runs

- Every request carries/gets a `trace_id`; pi.dev's task id is propagated into the
  trace so you can reconstruct "which agent, which deliberation, which model calls"
  across a whole parallel run.
- Aggregate metrics (queue depth, rack utilisation, per-caller share, effort mix,
  tokens/task) are exported so you can see whether pi.dev is saturating or starving
  the rack and tune replica count / caps accordingly.

## 6. Failure isolation

A parallel fleet needs one agent's failure to stay local:

- A stage crash or budget-exhaustion degrades that **one** request to "best answer so
  far" + an explicit trace note; it never takes down the replica.
- Backend hiccups (a vLLM restart) are retried within a request's budget, then
  surfaced as a normal error to that one caller — pi.dev's other agents are
  unaffected.
- The admission controller sheds load (queues/deprioritises) rather than cascading a
  failure across callers.
