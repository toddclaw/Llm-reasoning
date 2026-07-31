# Deliberate — a modular reasoning layer for local models

> **Working name: Deliberate** (System 2 = deliberation). Rename freely.
> The reasoning layer is now the **foundation**; [Nightshift](../plan/00-overview.md)
> becomes one consumer of it (see §6).

## 1. What it is, in one sentence

An **OpenAI-compatible proxy** that sits in front of your Qwen3.5 endpoint and turns
a single "answer this" call into a bounded, self-correcting, debiased reasoning
process — returning a better answer in the ordinary response shape, so **any client
(Claude Code, pi.dev, curl) gets the improvement by changing one `base_url`.**

```
client ──OpenAI /v1/chat/completions──▶  DELIBERATE  ──OpenAI──▶  vLLM (Qwen3.5)
   (Claude Code, pi.dev, your agent)     reasoning proxy          rack
        unchanged client                  stateless, scalable      unchanged model
```

Nothing about the client or the model changes. The reasoning lives **between** them,
in a layer you can version, test, share, and reuse.

## 2. Why Claude Code + Qwen3.5 underperforms — and why a layer fixes it

You observed Qwen3.5 doing far worse inside Claude Code than an Anthropic model
does. That is expected, and it is not mostly a weights problem. Claude Code's harness
is tuned end-to-end for Claude:

| Root cause | What actually happens with Qwen | Layer's fix (see [03](03-qwen-adaptation.md)) |
| ---------- | ------------------------------- | ---------------------------------------------- |
| **Tool-call format mismatch** | Claude Code emits Anthropic-style tool schemas + prompting; Qwen was trained on a different tool-call convention, so it mis-formats calls or narrates them as prose | Rewrite tool defs into Qwen's native format; parse tool calls under a grammar so they can't be malformed |
| **Claude-tuned system prompt** | A long prompt written for Claude's instruction-following; Qwen adheres less faithfully and drifts | Qwen-specific system-prompt shim + compression; move hard constraints into decode-time grammar |
| **No internal self-correction** | Claude silently reflects and fixes itself mid-response; Qwen commits to its first pass | External reflect / verify loops ([02](02-reasoning-modules.md)) |
| **Weak structured-output adherence** | JSON/format requests come back subtly wrong, breaking the agent loop | Grammar-constrained decoding for every structured output |
| **Overconfidence & substitution** | Qwen answers an easier nearby question confidently and doesn't flag it | The Inquiry & Debiasing stage ([02](02-reasoning-modules.md) §2) |

The through-line: **frontier "reasoning" is largely scaffolding built around the base
model.** Claude ships that scaffolding inside the product; with Qwen you have to
supply it yourself. Deliberate is that scaffolding, made external and portable.

## 3. The thesis, restated for a general-purpose layer

From the Nightshift work, unchanged and now the core principle of the layer:

> **Reliability comes from what the layer can check, not from what the model claims.**

Two consequences shape every module:

- **System 1 vs System 2 is a routing decision, not a default.** Kahneman's real
  lesson is that System 2 is *expensive and lazy for a reason* — you don't want it on
  every call. A cheap classifier decides how much deliberation a request earns, so
  simple prompts stay fast and only hard ones pay the latency ([01](01-architecture.md) §3).
- **Biases are mechanical, so debiasing can be mechanical.** The distinctive module
  (your idea) turns "what do I need to know to answer this?" and the classic
  cognitive biases into an explicit pre-flight checklist that runs *before* the model
  commits to an answer ([02](02-reasoning-modules.md) §2).

## 4. Design goals (the ones that make it shareable)

1. **Drop-in.** Full OpenAI Chat Completions compatibility, streaming included. If a
   tool works against OpenAI or vLLM, it works against Deliberate unchanged.
2. **Model-agnostic.** Qwen3.5 is the first *backend profile*, not a hard dependency.
   Any OpenAI-compatible backend works; the Qwen-specific behaviour is one pluggable
   profile. This is what lets you share it with someone running a different model.
3. **Modular.** Every reasoning strategy is a **stage plugin** behind one interface.
   Pipelines are declared in YAML — enable, reorder, budget, or replace stages
   without touching the core. Others can ship their own stages.
4. **Stateless & horizontally scalable.** A request carries its own reasoning
   lifecycle; replicas are interchangeable. This is what makes pi.dev's top-level
   parallelism trivial ([04](04-parallelism-and-pidev.md)).
5. **Honest.** The layer reports *calibrated confidence* and *residual unknowns*
   rather than laundering a guess into a confident answer.
6. **Measured.** A benchmark harness proves the lift (base vs base+layer) and
   ablates each stage, so you — and anyone you share it with — can see it actually
   helps before adopting it ([05](05-eval-and-roadmap.md)).

## 5. What you get and what it costs

- **Get:** materially better answers from the same weights; robust tool-calling and
  structured output with Qwen; explicit unknowns and calibrated confidence; a
  reusable component others can adopt with a URL change.
- **Cost:** latency and tokens. A high-effort deliberation may issue 5–30 model calls
  for one answer. This is acceptable precisely because your inference is abundant
  (H200 rack) — the layer trades your spare tokens for quality. Effort levels and the
  difficulty classifier keep the cost proportional to the task.

## 6. Relationship to Nightshift

Nightshift's agents currently each call a model directly. Under this design they call
**Deliberate** instead. The split:

| Concern | Lives in |
| ------- | -------- |
| Generic reasoning: framing, debiasing, plan-act-verify, best-of-N, reflection | **Deliberate** (shared, model-agnostic) |
| Qwen adaptation, grammar, tool-format | **Deliberate** |
| Domain gates, TDD/mutation/coverage, the scrum state machine, provenance/attestation | **Nightshift** (domain-specific) |

So Nightshift becomes "Deliberate + domain gates + workflow." Everything already
planned survives; the reasoning parts move down into a layer you can also use on its
own, or share, or point pi.dev at directly. See
[06-nightshift-integration.md](06-nightshift-integration.md) for the thin
integration contract.

## 7. Glossary

| Term | Meaning |
| ---- | ------- |
| **Stage** | A pluggable reasoning strategy implementing the `Stage` protocol. |
| **Pipeline** | An ordered, configured list of stages applied to a request. |
| **Backend profile** | Model-specific adaptation config (Qwen3.5 is the first). |
| **Framing Brief** | The Inquiry & Debiasing stage's structured output: reframed question, knowledge requirements, assumptions, disconfirmers, residual unknowns, calibrated confidence. |
| **Effort level** | `off \| low \| medium \| high` — how much deliberation a request earns. |
| **Trace** | The optional, structured record of what the layer did, returnable as response metadata. |
| **Verifier** | A pluggable check (deterministic where possible, judge-model otherwise) used by best-of-N and verify stages. |
