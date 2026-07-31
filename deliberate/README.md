# Deliberate

A modular, model-agnostic **reasoning proxy** for local models. It speaks the OpenAI
Chat Completions API, so any client (pi, Claude Code, curl, the OpenAI SDK) points at
it with a `base_url` change and gets improved behaviour on top of an unchanged model
and an unchanged client.

This directory is **Phase 0**: an OpenAI-compatible passthrough proxy plus the **Qwen
adaptation layer**. It is deliberately small and independently useful — it fixes the
"pi/Claude Code + Qwen underperforms" problem before any of the reasoning stages
(framing, best-of-N, reflection) exist. Those arrive in later phases; see
[`../docs/deliberate/`](../docs/deliberate/) for the full design and roadmap.

## What Phase 0 does

- **OpenAI-compatible endpoint** — `POST /v1/chat/completions` (streaming and
  non-streaming), `GET /v1/models`, `GET /health`.
- **Qwen tool-call recovery** — when Qwen narrates a tool call as text
  (`<tool_call>{...}</tool_call>` inside the message) instead of emitting structured
  `tool_calls`, Deliberate parses it out and returns a proper OpenAI `tool_calls`
  response. This is the single biggest cause of agent-loop breakage with Qwen.
- **Optional grammar-constrained structured output** — translate a request's
  `response_format` json_schema into vLLM `guided_json` (off by default).
- **Effort levels** — `reasoning_effort: off|low|medium|high`, or a model suffix
  (`base:high`). Parsed and echoed back now; drives reasoning stages in later phases.
- **Per-replica admission control** — a bounded number of concurrent backend calls,
  with callers queueing rather than failing at capacity.

Reasoning stages are **not** in Phase 0, so every effort level currently resolves to
passthrough reasoning; the Qwen adaptation applies regardless of effort because it is
a transport fix, not a reasoning stage.

## Quickstart

```bash
uv venv && uv pip install -e ".[dev]"

cp config.example.yaml config.yaml     # edit: point `endpoint` at your vLLM
deliberate serve --config config.yaml
```

Then point your client at `http://localhost:8080/v1`. For example, with pi, set its
model endpoint to that URL; every pi agent (including ones an orchestration extension
spawns in parallel) inherits the adaptation.

```bash
curl http://localhost:8080/v1/chat/completions -H 'content-type: application/json' -d '{
  "model": "base",
  "messages": [{"role": "user", "content": "What is 2+2?"}]
}'
```

## Configuration

See [`config.example.yaml`](config.example.yaml). One YAML file defines a deployment:
the upstream backend(s), the adaptation profile per backend, the admission cap, and
the default effort. Nothing tunable lives in code.

## Tests

```bash
uv run pytest
```

Covers effort parsing/precedence, Qwen tool-call recovery (well-formed, multiple,
`parameters` alias, string args, malformed-left-intact, already-structured
passthrough), SSE synthesis, and the server end-to-end against a mocked backend
(passthrough, tool recovery, streaming both ways, upstream-model rewriting, error
propagation).

### Live smoke test (against a real Qwen endpoint)

`scripts/live_smoke.py` runs the full adapter path against a real OpenAI-compatible
Qwen endpoint (no server process needed; honours `HTTPS_PROXY`):

```bash
export DELIBERATE_UPSTREAM_URL="https://openrouter.ai/api/v1"   # any OpenAI-compatible base
export DELIBERATE_UPSTREAM_MODEL="qwen/qwen3-235b-a22b"         # a Qwen-family model
export DELIBERATE_UPSTREAM_KEY="sk-..."
uv run python scripts/live_smoke.py
```

It checks transparency (stream + non-stream) and tool calling. **Note:** the
`<tool_call>`-recovery path only fires when the serving stack didn't already parse
tool calls — most hosted providers do, so recovery is best proven against your own
vLLM started *without* `--tool-call-parser`. The script's recovery check is
best-effort and only warns.

## Layout

```
src/deliberate/
  config.py       deployment config model + loader
  effort.py       effort levels + parsing (field, model-suffix, default)
  admission.py    per-replica concurrency cap
  backend.py      async client for an upstream OpenAI-compatible endpoint
  adapt/          profiles: base (passthrough) + qwen (tool-call recovery, guided json)
  stream.py       synthesize an SSE stream from a full completion (tool-bearing requests)
  server.py       FastAPI app: /v1/chat/completions, /v1/models, /health
  cli.py          `deliberate serve|version`
```

This maps to the fuller package layout in the design doc; it is expanded (stages/,
verifiers/, classify/, trace/) in later phases.

## License

Apache-2.0.
