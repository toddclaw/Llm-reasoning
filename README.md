# Nightshift

An offline, multi-agent software engineering system that turns a Claude-Code-style
request into finished, verified, documented work — using small local models
(Qwen3 / Qwen3-Coder class) instead of a frontier model.

The bet: frontier models are not mostly better *base* models, they are base models
wrapped in reasoning, tool discipline, and self-correction. That wrapper can be
built **outside** the weights. With locally-hosted frontier-class open models
(Qwen3.5-397B-A17B + Qwen3-Coder-Next, FP8) the scaffold is no longer compensating
for weak weights — it is buying **trust**: verifiable, provenance-backed output you
can accept unseen in the morning. The "small model + strong System 2" experiment is
preserved as an eval axis.

**Working name:** Nightshift (it runs while you sleep). Rename freely.

## Deployment shape

Three trust tiers (see [05](docs/plan/05-inference-and-topology.md)): an **H200 rack**
serves both models via vLLM; an **air-gapped laptop** runs the agents (in a podman
container with no SSH keys, no internet, no git-push), owns the attestation key, and
runs the compile/test gates; a **Proxmox target** of isolated QEMU VMs runs the
software under evaluation with no route back. Two work paths, chosen at session start:
**BUILD** (forward development) and **INVESTIGATE** (RE/VR) — see
[10](docs/plan/10-dual-path-and-existing-repos.md).

## Status

Planning. Nothing implemented yet. Open questions have been answered by the human
(see [09](docs/plan/09-open-questions.md)) and the plan revised accordingly. Written
to be executed by Claude Opus in Claude Code.

## Read the plan in order

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
