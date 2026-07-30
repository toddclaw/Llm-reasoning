# Nightshift

An offline, multi-agent software engineering system that turns a Claude-Code-style
request into finished, verified, documented work — using small local models
(Qwen3 / Qwen3-Coder class) instead of a frontier model.

The bet: frontier models are not mostly better *base* models, they are base models
wrapped in reasoning, tool discipline, and self-correction. That wrapper can be
built **outside** the weights. A 30B model with a rigorous external System 2 should
beat a 30B model asked nicely.

**Working name:** Nightshift (it runs while you sleep). Rename freely.

## Status

Planning. Nothing implemented yet. The plan below is written to be executed by
Claude Opus in Claude Code.

## Read the plan in order

| Doc | What it covers |
| --- | --- |
| [00-overview.md](docs/plan/00-overview.md) | Thesis, System 1 / System 2 mapping, design principles, glossary |
| [01-architecture.md](docs/plan/01-architecture.md) | Components, artifact schemas, story state machine, git model, tech stack |
| [02-agents.md](docs/plan/02-agents.md) | The scrum roster, agent contracts, model routing, context assembly |
| [03-verification.md](docs/plan/03-verification.md) | The gate battery — how the four known failure modes are killed mechanically |
| [04-eval-and-iteration.md](docs/plan/04-eval-and-iteration.md) | Task suite, scoring, playbook sweeps, how we iterate until it's good |
| [05-model-serving-offline.md](docs/plan/05-model-serving-offline.md) | Local inference stack, quantization, multiplexing, air-gapped supply chain |
| [06-domain-playbooks.md](docs/plan/06-domain-playbooks.md) | C++, Python, Bash, reverse engineering, vulnerability research |
| [07-overnight-autonomy.md](docs/plan/07-overnight-autonomy.md) | Budgets, deadlock detection, escalation ladder, morning report |
| [08-roadmap.md](docs/plan/08-roadmap.md) | Phases with measurable exit criteria |
| [09-open-questions.md](docs/plan/09-open-questions.md) | Decisions needed from the human |

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
