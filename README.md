# Llm-reasoning — Deliberate + Nightshift

Two layers, one thesis: **frontier models are mostly base models wrapped in
reasoning, tool discipline, and self-correction — and that wrapper can be built
outside the weights.**

- **[Deliberate](docs/deliberate/00-overview.md)** — the **foundation**: a modular,
  model-agnostic, OpenAI-compatible **reasoning proxy** that sits in front of a local
  model (Qwen3.5) and turns one "answer this" call into a bounded, self-correcting,
  *debiased* reasoning process. Drop-in (`base_url` swap), shareable, and designed for
  **pi.dev** to orchestrate in parallel above it. This is the piece you can hand to
  someone else.
- **[Nightshift](docs/plan/00-overview.md)** — a **consumer** of Deliberate: an
  offline, multi-agent software-engineering and RE/VR system that adds domain gates,
  provenance, and a scrum/investigate workflow on top of the reasoning layer.

**Why this exists:** Claude Code with Qwen3.5 underperforms badly versus Anthropic
models, because Claude Code's harness is tuned for Claude. Deliberate supplies the
missing scaffolding — Qwen-native tool-calling and grammar, plus explicit reasoning
and debiasing — as an external, portable layer.

**Working names:** *Deliberate* (System 2 = deliberation) and *Nightshift* (it runs
while you sleep). Rename freely.

**Status:** planning; nothing implemented yet. Design decisions have been made
interactively with the human (see the Deliberate docs and
[the Nightshift open questions](docs/plan/09-open-questions.md)). Written to be
executed by Claude Opus in Claude Code. Suggested build order: **Deliberate Phase 0**
(the Qwen adapter) first — it fixes the immediate Claude-Code + Qwen pain and is
shippable on its own.

---

## Layer 1 — Deliberate (the reasoning proxy)

| Doc | What it covers |
| --- | --- |
| [00-overview.md](docs/deliberate/00-overview.md) | What it is, why Claude+Qwen underperforms, design goals |
| [01-architecture.md](docs/deliberate/01-architecture.md) | Request lifecycle, stage plugin API, effort levels, statelessness, streaming, config |
| [02-reasoning-modules.md](docs/deliberate/02-reasoning-modules.md) | The stages — incl. the **Inquiry & Debiasing** (Kahneman) module in detail |
| [03-qwen-adaptation.md](docs/deliberate/03-qwen-adaptation.md) | Tool-format translation, grammar, prompt shims — the direct fix for the Claude-Code pain |
| [04-parallelism-and-pidev.md](docs/deliberate/04-parallelism-and-pidev.md) | pi.dev above the layer, admission control, horizontal scaling |
| [05-eval-and-roadmap.md](docs/deliberate/05-eval-and-roadmap.md) | Measuring the lift, ablations, phased roadmap |
| [06-nightshift-integration.md](docs/deliberate/06-nightshift-integration.md) | The thin contract between the two layers |

---

## Layer 2 — Nightshift (the consumer)

An offline, multi-agent software-engineering and RE/VR system that turns a
Claude-Code-style request into finished, verified, documented work — built **on top
of Deliberate** and adding domain gates, provenance, and a scrum/investigate
workflow.

**Deployment shape.** Four trust tiers (see
[05](docs/plan/05-inference-and-topology.md)): an **H200 rack** serves both models via
vLLM; an **air-gapped laptop** runs the agents (podman, no SSH keys, no internet, no
git-push) and owns the attestation key; a **Proxmox build/test VM** runs the
compile/test gates; **Proxmox target VMs** run the software under evaluation with no
route back. Two work paths, chosen at session start: **BUILD** (forward development)
and **INVESTIGATE** (RE/VR) — see [10](docs/plan/10-dual-path-and-existing-repos.md).

### Nightshift plan docs, in order

| Doc | What it covers |
| --- | --- |
| [00-overview.md](docs/plan/00-overview.md) | Thesis, System 1 / System 2 mapping, design principles, glossary |
| [01-architecture.md](docs/plan/01-architecture.md) | Components, artifact schemas, story state machine, git model, tech stack |
| [02-agents.md](docs/plan/02-agents.md) | The scrum roster, agent contracts, model routing, context assembly |
| [03-verification.md](docs/plan/03-verification.md) | The gate battery — how the four known failure modes are killed mechanically |
| [04-eval-and-iteration.md](docs/plan/04-eval-and-iteration.md) | Task suite, scoring, playbook sweeps, how we iterate until it's good |
| [05-inference-and-topology.md](docs/plan/05-inference-and-topology.md) | H200 rack + laptop + Proxmox topology, vLLM/FP8, the resource inversion, offline supply chain |
| [06-domain-playbooks.md](docs/plan/06-domain-playbooks.md) | C++, Python, Bash, reverse engineering, vulnerability research |
| [07-overnight-autonomy.md](docs/plan/07-overnight-autonomy.md) | Budgets, deadlock detection, escalation ladder, morning report |
| [08-roadmap.md](docs/plan/08-roadmap.md) | Phases with measurable exit criteria |
| [09-open-questions.md](docs/plan/09-open-questions.md) | Decisions needed from the human (with answers) |
| [10-dual-path-and-existing-repos.md](docs/plan/10-dual-path-and-existing-repos.md) | The BUILD vs INVESTIGATE paths, and existing-codebase support (Cartographer, blast-radius control) |

## The one-paragraph version

A deterministic workflow engine routes each story through a state machine
(`SHAPED → ARCHITECTED → RED → GREEN → REFACTORED → REVIEWED → INTEGRATED →
DEMONSTRATED → DOCUMENTED → ACCEPTED`). Specialised agents are *state handlers*,
not chat participants: each gets a freshly assembled, tightly bounded context and
emits a schema-validated artifact. Between every state sits a **gate** — a
deterministic predicate over evidence produced by the harness, never over claims
made by a model. Agents cannot report that tests pass; only the test runner can.
An eval harness scores the whole scaffold against a task suite with hidden
oracles, so the reasoning structure can be tuned like any other system under test.
