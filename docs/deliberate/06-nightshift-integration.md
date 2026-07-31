# 06 — Nightshift Integration Contract

Nightshift becomes a **consumer** of Deliberate. This is a thin, deliberate seam so
the two projects evolve independently and Deliberate stays usable on its own.

## 1. What moves where

| Concern | Before (Nightshift plan) | After |
| ------- | ------------------------ | ----- |
| Talking to the model (tool-format, grammar, thinking-mode, prompt-cache layout) | Nightshift `models/` | **Deliberate** (Qwen profile) |
| Generic reasoning (framing/debiasing, reflect, best-of-N, plan-act-verify) | scattered in Nightshift agents/ladder | **Deliberate** stages |
| Model routing by class (REASONER/CODER/JUDGE/CHEAP) | Nightshift router | **Deliberate** backends + effort; Nightshift picks effort per role |
| Domain gates (TDD, mutation, coverage, sanitizers, from-scratch build, demo) | Nightshift `gates/` `runners/` | **Nightshift** (unchanged) |
| Provenance/attestation, blackboard, worktrees | Nightshift | **Nightshift** (unchanged) |
| Scrum + investigate state machines, escalation ladder | Nightshift | **Nightshift** (unchanged) |

Rule of thumb: **Deliberate decides *how to think*; Nightshift decides *what work to
do and how to prove it*.** Deliberate has no idea what a "story" or a "gate" is;
Nightshift has no idea what "anchoring bias" or "best-of-N" is.

## 2. The seam

Each Nightshift agent call becomes a Deliberate request:

```
Nightshift agent invoke(role, story, state)
  → assemble_context(...)                     # Nightshift: role-specific context
  → POST base_url=DELIBERATE /v1/chat/completions
        model:            qwen3.5             # or coder profile
        reasoning_effort: <per-role>          # architect=high, extraction=low
        response_format:  <role output schema># Deliberate grammar-constrains it
        tools:            <role tool allowlist>
        x-deliberate-trace: full              # Nightshift stores the trace as an artifact
  → validated artifact
```

- **Effort per role** replaces some of Nightshift's bespoke ladder logic: the
  Architect calls at `high`, an extraction step at `low`. Nightshift still owns the
  *gate-driven* retry ladder; Deliberate owns the *within-call* reasoning.
- **The Framing Brief becomes a first-class Nightshift artifact.** An agent's
  `residual_unknowns` from `frame` map naturally onto Nightshift's parked-question /
  clarifying-question mechanism — the honesty artifacts line up.
- **Verification stays split correctly.** Deliberate's soft verifiers (judge,
  consistency) improve the *draft*; Nightshift's hard gates (real tests, mutation,
  container demo) remain the source of truth. Deliberate never claims a Nightshift
  gate passed — provenance still lives entirely in Nightshift.

## 3. Why this ordering is safe

- Deliberate Phase 0 (the Qwen adapter) already helps Nightshift even before any
  Deliberate reasoning stages exist — Nightshift just gets robust tool-calls and
  structured output for free.
- Nightshift's gate battery is unchanged, so nothing about correctness/trust depends
  on Deliberate being finished. If a Deliberate stage regresses, Nightshift's gates
  still catch bad output — the safety net doesn't move.
- You can develop and share Deliberate on its own timeline; Nightshift adopts it when
  its Phase 6 arrives ([05](05-eval-and-roadmap.md) §3).

## 4. Boundary tests

- A test asserts Nightshift makes **no direct** backend calls — everything goes
  through Deliberate — so the seam doesn't erode over time.
- A test asserts Deliberate has **no** Nightshift concepts in its dependency graph
  (no "story", "gate", "attestation") — so it stays a shareable, general-purpose
  layer.
