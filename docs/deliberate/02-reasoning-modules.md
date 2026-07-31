# 02 — Reasoning Modules (Stages)

Five built-in stages ship in the core. Each is independently testable, independently
skippable, and composed via config. Order in the default pipeline:

```
classify → frame → plan_act_verify → best_of_n → reflect → (answer)
```

`frame` is the distinctive one (your idea) and is described first and at length.

---

## 2. Stage: `frame` — Inquiry & Debiasing (the Kahneman pre-flight)

**The core insight you added:** before the model commits to an answer, make it
answer a different question first — *"what do I need to know to answer this well, and
where am I about to fool myself?"* This runs **before** any answer is drafted, so it
shapes the answer rather than critiquing it after the fact (that's `reflect`'s job).

The stage produces a **Framing Brief** into `scratch["framing_brief"]`, which every
downstream stage consumes and which can be surfaced to the caller as trace.

### 2.1 Phase A — Inquiry ("What do I need to know?")

A grammar-constrained call that produces, not prose, a structured brief:

```
FramingBrief:
  asked_question:      restatement in the asker's terms
  reframes:            same question posed inversely / from another framing
  substitution_check:  is there an easier question I'm tempted to answer instead?
                       (Kahneman's central mechanism) — name it if so
  knowledge_requirements: [
    { need: "…", status: in_context | retrievable | unknown | assumption,
      source_hint: "…" }
  ]
  assumptions:         the ones I'm making explicit rather than smuggling in
  answer_shape:        what a good answer must contain to actually settle the question
```

Then the stage **acts on the requirements it can**:

- `retrievable` needs fire the configured tools — RAG over a local corpus, the
  caller's own tools (if this is an agent request with tools), or a targeted
  sub-query to the model. Retrieved facts land in `scratch` with provenance and are
  injected into the answer context.
- `unknown` needs that block a correct answer become either (a) **clarifying
  questions** returned to an agentic caller, or (b) explicit caveats in the final
  answer. The layer does not paper over a genuine unknown with fluent text.
- `assumption` needs are surfaced in the final answer's "assumptions" note when they
  are load-bearing.

This directly attacks Qwen's most damaging habit: **answering an easier, adjacent
question confidently.** Naming the substitution up front is often the whole fix.

### 2.2 Phase B — Debiasing checklist

Each check is a small, targeted probe, run **only when relevant** (the classifier and
`answer_shape` decide which apply — you don't run the anchoring check on a request
with no numbers). Each yields a note that conditions the answer.

| Bias (Kahneman) | The probe the stage runs | What it prevents |
| --------------- | ------------------------ | ---------------- |
| **Substitution** | "Am I answering the asked question or an easier cousin?" | Confidently-wrong off-target answers |
| **WYSIATI** (what you see is all there is) | "What absent information would change the answer? Am I treating 'not mentioned' as 'not relevant'?" | Overconfident answers from incomplete context |
| **Anchoring** | "Is an early number / example / the user's framing dominating my estimate?" | Getting pulled to a stated starting point |
| **Availability / representativeness** | "Am I using base rates and the outside view, or just what's easy to recall?" | Vivid-but-unrepresentative reasoning |
| **Confirmation** | "State the strongest disconfirming evidence and the best *alternative* answer." | One-sided reasoning |
| **Overconfidence / planning fallacy** | "Give a calibrated confidence and the conditions under which this is wrong." | False certainty; underestimated effort |
| **Framing / loss-aversion** | "Re-pose positively and negatively — do the answers diverge?" | Presentation-driven flips |
| **Sunk cost / consistency** *(agentic loops)* | "Am I continuing a plan only because I started it?" | Doubling down on a bad trajectory |

Output merged into the Framing Brief:
`{ disconfirmers_considered, best_alternative, calibrated_confidence, residual_unknowns }`.

### 2.3 Why this is worth a whole stage

- It's the cheapest large-quality lever for a *single-shot* answer — no N-sampling
  required, just one structured pre-flight — so it earns its place even at `low`
  effort.
- It produces the **honesty artifacts** (unknowns, calibrated confidence,
  assumptions) that make the layer trustworthy, which pure "think step by step" does
  not.
- It is **measurable**: the eval harness scores calibration (does stated confidence
  track actual correctness?) and substitution-catch rate on a planted-substitution
  task set ([05](05-eval-and-roadmap.md)).

**Guardrail against over-thinking:** the stage is proportional to difficulty and can
*shrink* an answer's confidence but is explicitly forbidden from manufacturing
complexity on simple requests — the eval includes an "easy questions stay easy and
correct" regression so debiasing doesn't degrade good System-1 answers.

---

## 3. The other four stages

### 3.1 `plan_act_verify`
Decompose the task into bounded steps; execute each; **verify each against evidence**
before proceeding. Verification uses the pluggable verifiers (§4). A step that fails
verification is retried or the plan is revised, up to `max_steps`. This is the
general-purpose form of Nightshift's state machine — same discipline, no domain
assumptions. Best for multi-step tasks (code, math, structured analysis); the
classifier skips it for one-shot Q&A.

### 3.2 `best_of_n`
Sample N candidate answers in parallel (one async fan-out, cheap on the rack), then
**select**:
- if a *deterministic* verifier applies (code runs, math checks, schema validates,
  retrieval-grounded) → filter to passing candidates, then pick shortest/simplest;
- else → a **judge** call (decorrelated backend, `seed_offset`) scores against
  `answer_shape` from the Framing Brief and picks the best.
Two-stage funnel from Nightshift applies when verification is expensive: a cheap
static check culls before the expensive one runs. N and selector are config.

### 3.3 `reflect`
Draft → critique with **fresh context** (the critic doesn't see the drafting
rationale, so it doesn't rubber-stamp) → revise. `rounds` configurable (default 1).
Cheap, general, and the single most broadly useful stage after `frame`. The critic is
pointed at `answer_shape` and the debiasing notes, so it checks the *right* things.

### 3.4 `passthrough`
The identity stage: forward to the backend unchanged (still through the Qwen adapter
for tool-format/grammar fixes). What `effort: off` and trivial requests resolve to.
Its existence is what makes it safe to route *all* traffic through Deliberate.

---

## 4. Verifiers (shared by `plan_act_verify` and `best_of_n`)

Verification is pluggable because a general-purpose layer can't assume a test
harness. Ordered by trustworthiness — always prefer a deterministic check:

| Verifier | Kind | Applies to |
| -------- | ---- | ---------- |
| `exec` | run code/math in a sandbox, compare output | code, arithmetic, anything executable |
| `jsonschema` | validate structured output | API responses, tool args, structured extraction |
| `retrieval` | check claims are grounded in retrieved sources | factual Q&A over a corpus |
| `consistency` | self-consistency across N samples (agreement) | reasoning with no external oracle |
| `judge` | decorrelated model scores against a rubric | the fallback when nothing better exists |

The layer **reports which verifier backed a result** and never upgrades a
judge-model opinion to the status of an executed check. When only `judge` or
`consistency` was available, the calibrated confidence reflects that — this is how
the layer stays honest about soft verification.

---

## 5. Writing your own stage (the sharing story)

A third party adds a reasoning strategy without forking:

```python
# my_pkg/stages.py
class DebateStage:
    id = "debate"
    def applicable(self, s): return s.request.effort >= Effort.HIGH
    async def run(self, s):
        # spawn two personas, adjudicate; append to s.trace; evolve s.messages
        return s
```

```toml
# pyproject.toml
[project.entry-points."deliberate.stages"]
debate = "my_pkg.stages:DebateStage"
```

`pip install my_pkg`, then add `debate` to a pipeline in YAML. That is the entire
extension surface — one protocol, one entry point, config to wire it in. It's what
makes "share it with others" real: they get your stages the same way, and can
contribute theirs back.
