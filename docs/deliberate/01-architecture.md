# 01 — Architecture

## 1. Request lifecycle

```
POST /v1/chat/completions
        │
        ▼
┌──────────────────────────────────────────────────────────────────┐
│ INGRESS                                                          │
│  parse OpenAI request · extract effort hint · auth · rate-limit  │
└───────────────┬──────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ CLASSIFY  (cheap, one call or heuristic)                         │
│  difficulty · task kind · needs-tools? · effort ⇒ pipeline pick  │
│  trivial ⇒ short-circuit to PASSTHROUGH                          │
└───────────────┬──────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ PIPELINE  (ordered stages, from config)                          │
│   frame → plan_act_verify → best_of_n → reflect  (example)       │
│   each stage: (ReasoningState) -> ReasoningState                 │
│   every model call goes through the ADAPTER (Qwen profile)       │
└───────────────┬──────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ EGRESS                                                           │
│  render final answer in OpenAI shape · stream · attach trace     │
│  (as metadata; never breaks a vanilla OpenAI client)             │
└──────────────────────────────────────────────────────────────────┘
                │
                ▼        every model call ↓
        ┌────────────────────────────────────────────────┐
        │ ADAPTER + BACKEND CLIENT                        │
        │  Qwen tool-format · GBNF grammar · prompt shim  │
        │  admission control ⇒ vLLM (shared rack)         │
        └────────────────────────────────────────────────┘
```

The client sees a normal (if slower) completion. Everything between CLASSIFY and
EGRESS is the layer, and it is entirely optional per request — `effort: off` is a
pure passthrough, which is what keeps it safe to put in front of *all* traffic.

## 2. Core abstractions

Small, boring, testable. The whole point is that the interesting behaviour lives in
independently shippable stages, not in a clever core.

```python
class ReasoningState:
    request: OpenAIRequest          # the original, untouched
    messages: list[Message]         # working conversation the stages evolve
    scratch: dict[str, Any]         # inter-stage blackboard (e.g. the Framing Brief)
    trace: list[TraceEvent]         # what happened, for observability + eval
    budget: Budget                  # tokens / wall / model-calls left
    backend: Backend                # adapter-wrapped model client(s)

class Stage(Protocol):
    id: str
    def applicable(self, state: ReasoningState) -> bool: ...
    async def run(self, state: ReasoningState) -> ReasoningState: ...

class Backend(Protocol):            # adapter-wrapped; see 03-qwen-adaptation
    async def complete(self, msgs, *, grammar=None, tools=None,
                       sampling=None, n=1) -> list[Completion]: ...
```

Rules that keep it modular:

- **A stage only reads/writes `messages`, `scratch`, and `trace`.** It never reaches
  into another stage. Communication is through `scratch` keys with documented
  schemas (e.g. `scratch["framing_brief"]`).
- **A stage must be skippable.** `applicable()` lets the classifier/effort gate drop
  it; the pipeline still produces a valid answer without it.
- **A stage must respect `budget`.** Running out of budget is a normal outcome that
  degrades gracefully to "return best answer so far", never a crash.
- **The core ships ~5 built-in stages; everyone else's live as plugins** discovered
  via entry points, so sharing a new reasoning strategy is `pip install`-able.

## 3. Effort levels and the difficulty classifier

Kahneman's actual thesis is that System 2 is costly and should be *recruited
selectively*. So deliberation is gated two ways:

**Effort (caller-controlled).** Exposed without breaking OpenAI clients, in priority
order:
1. explicit request field `reasoning_effort: off|low|medium|high` (mirrors the
   familiar OpenAI-style knob),
2. a model-name suffix — `qwen3.5` vs `qwen3.5:high` — for clients that can only set
   the model string (Claude Code can),
3. server default from config.

**Difficulty (server-inferred).** A cheap classifier (a small-model call or, for very
short prompts, heuristics) estimates task hardness and kind, and maps
`effort × difficulty → pipeline`. An easy factual question at `medium` still
short-circuits; a subtle multi-constraint task at `low` still gets the framing stage.

| effort \ difficulty | trivial | moderate | hard |
| ------------------- | ------- | -------- | ---- |
| off | passthrough | passthrough | passthrough |
| low | passthrough | frame → reflect | frame → reflect → verify |
| medium | passthrough | frame → PAV → reflect | frame → PAV → best_of_n(3) → reflect |
| high | frame → reflect | frame → PAV → best_of_n(5) → reflect | full pipeline, best_of_n(8), self-consistency |

The table is **config**, not code — it is the primary thing you tune and the primary
thing the eval harness sweeps ([05](05-eval-and-roadmap.md)).

## 4. Statelessness (why pi.dev parallelism is free)

Each request is self-contained: all reasoning state is constructed at ingress and
discarded at egress. No cross-request memory in the default path. Consequences:

- **Replicas are interchangeable.** Run K Deliberate processes behind a load
  balancer; pi.dev fans out across them with no affinity requirement.
- **Idempotent under a seed.** `(request, seed)` reproduces the trajectory, which is
  what makes the eval harness and debugging tractable.
- **Optional session store, explicit and external.** If a caller *wants* continuity
  (a persistent scratch across turns), it passes a `session_id` and the layer reads/
  writes a pluggable KV store (Redis/SQLite). Off by default; never implicit. This
  keeps the common case trivially scalable and makes stateful use opt-in.

## 5. Streaming

Clients like Claude Code expect SSE streaming. The layer:

- Runs the pipeline internally (non-streamed model calls, since stages need whole
  outputs to inspect), then **streams the final answer** token-by-token from the last
  stage. To the client it looks like a normal streamed completion that started
  "thinking" first.
- Optionally emits **progress events** as SSE comments (`: stage=frame`) that
  standard clients ignore but a Deliberate-aware UI can render. Never in the content
  channel, so it can't corrupt a tool-call parse.
- **Time-to-first-token will be higher.** This is the honest cost of deliberation;
  the effort gate is how a latency-sensitive caller opts out per request.

## 6. Trace and observability

Every stage appends structured `TraceEvent`s: which stage, inputs digest, model
calls, verifier results, tokens, wall time, and stage-specific payloads (e.g. the
Framing Brief). The trace is:

- returned **as response metadata** when the client opts in
  (`x-deliberate-trace: full`) — placed in a non-standard response field so vanilla
  OpenAI clients ignore it,
- always written to structured logs (JSONL) for the eval harness and for debugging,
- the substrate for a later local trace-viewer UI.

Trace discipline mirrors Nightshift's provenance rule: a `TraceEvent` that records a
*verifier result* is produced by the verifier, not narrated by the model. This is
what lets "confidence" mean something.

## 7. Config

One YAML file defines a deployment. Everything tunable lives here, nothing in code.

```yaml
server:
  host: 0.0.0.0
  port: 8080
  max_concurrent_requests: 64        # admission control to the rack (see 04)

backends:
  base:
    endpoint: http://rack:8000/v1
    model: Qwen3.5-397B-A17B-FP8
    profile: qwen3                    # the adaptation profile (03)
  judge:
    endpoint: http://rack:8000/v1
    model: Qwen3.5-397B-A17B-FP8
    profile: qwen3
    seed_offset: 7919                 # decorrelate the judge

defaults:
  reasoning_effort: medium

classifier:
  model: base
  cheap_heuristics: true             # skip the call for very short prompts

pipelines:                            # effort×difficulty → pipeline (the §3 table)
  medium.hard: [frame, plan_act_verify, best_of_n, reflect]
  # ...

stages:
  frame:        { debias_checks: [substitution, wysiati, anchoring, overconfidence] }
  best_of_n:    { n: 5, verifier: auto, selector: judge }
  plan_act_verify: { max_steps: 6 }
  reflect:      { rounds: 1 }

verifiers:                            # pluggable; see 02 §4
  code:  { kind: exec, sandbox: local }
  math:  { kind: exec }
  schema:{ kind: jsonschema }
  default: { kind: judge, backend: judge }
```

## 8. Tech stack

| Concern | Choice | Why |
| ------- | ------ | --- |
| Language | Python 3.12 (async) | ecosystem + async fan-out for best-of-N |
| Server | FastAPI + `sse-starlette` | OpenAI-compatible routes, streaming |
| Backend client | `httpx` async to any OpenAI-compatible endpoint | model-agnostic |
| Schemas | pydantic v2 | requests, config, stage I/O, JSON-Schema→GBNF |
| Grammar | vLLM `guided_json`/XGrammar (or GBNF passthrough) | structured output ([03](03-qwen-adaptation.md)) |
| Plugins | Python entry points (`deliberate.stages`) | shareable third-party stages |
| Packaging | `uv`; published wheel + Docker image | `pip install deliberate` / `deliberate serve` |
| Config | YAML + pydantic-settings | one-file deployments |
| Logging | `structlog` → JSONL | trace = eval input |
| **Not used** | LangChain / CrewAI / AutoGen | the pipeline *is* the product; frameworks hide it |

## 9. Package layout

```
deliberate/
  server/        fastapi app, openai routes, streaming, ingress/egress
  core/          ReasoningState, Stage protocol, pipeline runner, budget
  classify/      difficulty + task-kind classifier
  stages/        frame/ plan_act_verify/ best_of_n/ reflect/ passthrough/
  adapt/         backend profiles: qwen3/, openai/, generic/
  verifiers/     exec/ jsonschema/ retrieval/ judge/
  backends/      httpx client, admission controller, retries
  trace/         events, redaction, exporters
  config/        schema, loader
  cli.py         `deliberate serve|bench|trace`
profiles/        qwen3.yaml, ...
pipelines/       default.yaml, experiments/*.yaml
bench/           tasks + graders (05)
```
