# 03 — The Qwen Adaptation Layer

This is the module that most directly fixes "Claude Code + Qwen3.5 underperforms." It
wraps **every** backend call — every stage inherits it — so the reasoning modules
never have to think about model-specific quirks.

A **backend profile** is a bundle of model-specific adaptations. `qwen3` is the first;
`openai` and `generic` profiles exist so the layer is genuinely model-agnostic and
shareable with people running other models.

## 1. Tool-call format translation

The biggest single cause of Qwen underperformance in a Claude-tuned harness.

- **Inbound:** the client (e.g. Claude Code) sends tool definitions in the
  OpenAI/Anthropic style. The profile rewrites them into the exact format Qwen was
  trained on (Qwen's tool/function-call convention and special tokens), including the
  system-prompt scaffolding Qwen expects around tools.
- **Decode-time constraint:** tool calls are generated under a **grammar** derived
  from the tool's JSON Schema, so Qwen physically cannot emit a malformed call or
  narrate a call as prose ("I would call search(...)"). This removes the single most
  common agent-loop breakage.
- **Outbound:** parse Qwen's tool-call output and re-emit it in the OpenAI
  `tool_calls` shape the client expects. The client remains blissfully unaware it's
  talking to Qwen.
- **Robust recovery:** if a call still can't be parsed, the adapter reprompts with a
  tightened grammar (a `DECODE_FAILURE` retry, separate from the reasoning budget)
  before surfacing an error — never returns a half-parsed call.

## 2. Grammar-constrained structured output

Any stage that needs structured output (the Framing Brief, a plan, a judge
scorecard, a candidate ranking) declares a pydantic schema; the adapter compiles it
to GBNF/`guided_json` and constrains decoding. Guidance carried over from Nightshift:

- keep schemas **shallow and flat** — deep nesting degrades small-model output and
  speed;
- constrain enums tightly (free correctness);
- **bound free-text field lengths** in the grammar — unbounded free text is where
  repetition loops happen;
- always set `max_tokens` and detect truncation explicitly (a truncated
  grammar-constrained response is invalid and is retried, not silently accepted);
- on decode failure, retry with a **simplified schema** (drop optional fields) before
  failing — cheap robustness given abundant inference.

## 3. System-prompt shimming

- Claude-tuned system prompts are long and lean on Claude's instruction-following.
  The profile can **compress and re-express** them into a form Qwen follows more
  faithfully, and moves hard constraints out of prose and into grammar where possible
  (a constraint the model *can't* violate beats a constraint it's *asked* not to).
- Inject Qwen-appropriate role/format scaffolding the client didn't provide.
- All rewrites are **profile config + templates**, versioned and eval-swept — not
  hidden magic. You can see and tune exactly what the layer injects.

## 4. Thinking-mode control

Qwen3-family models expose a hybrid thinking mode. The profile controls it **per
stage**, because the right setting differs by role:

- `frame`, `plan_act_verify`, judge → thinking usually **on**;
- extraction, classification, tool-arg generation → thinking **off** (wasted tokens
  and can hurt format adherence);
- `auto` defers to the classifier.

Treated as a swept parameter ([05](05-eval-and-roadmap.md)), never assumed. When
thinking is on, the thinking span is **stripped from the answer returned to the
client** and preserved only in the trace — clients expect an answer, not the model's
scratchpad.

## 5. Sampling and determinism

- Per-stage sampling profiles (temp/top_p/repeat_penalty/max_tokens) in the profile
  config: low temperature for judging and extraction, higher for best-of-N diversity.
- Seed control for reproducibility; `seed_offset` decorrelates the judge from the
  generator so "independent review" is actually independent.
- Note (carried from Nightshift): with vLLM, pin the config needed for reproducible
  decoding in the eval profile; determinism is a property you have to arrange.

## 6. Prompt-cache-friendly layout

vLLM automatic prefix caching rewards a stable prefix. The adapter assembles every
prompt as **[stable prefix: profile scaffolding · tool defs · system shim · task
context] + [volatile suffix: prior-stage evidence · the specific ask]**, and never
interpolates timestamps/ids above the volatile line. Across a multi-stage
deliberation (many calls sharing most context) this is a large latency win. A
regression test asserts prefix stability.

## 7. Why the profile is the shareability seam

Because all model-specific behaviour is isolated in the profile:

- Someone running a **different** model writes a new profile (or uses `generic`) and
  gets every reasoning stage unchanged — the layer is not Qwen-locked.
- Improving Qwen support (a better tool-format, a new thinking heuristic) is a profile
  change others can adopt without touching their pipelines.
- The eval harness can **A/B two profiles** on the same tasks, so profile tuning is
  measured, not guessed.

The division of labour is the whole design: **stages are what reasoning to do;
profiles are how to talk to this particular model.** Keeping them orthogonal is what
lets you share the reasoning with people who don't run Qwen, and share Qwen fixes
with people who don't use your pipelines.
