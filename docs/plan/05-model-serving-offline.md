# 05 — Model Serving and the Air-Gapped Supply Chain

## 1. Inference stack

**Recommendation: `llama.cpp` (`llama-server`) behind `llama-swap`.**

Rationale for a laptop:

- GGUF + partial GPU offload works across CUDA / Metal / ROCm / pure CPU, so the
  system is portable across whatever hardware you end up on.
- **GBNF grammar-constrained decoding is first-class** — this is non-negotiable for
  P4, and it is the single most important feature we need from the runtime.
- `llama-swap` gives one OpenAI-compatible endpoint with automatic model
  load/unload and TTL-based eviction, which is exactly the multiplexing we need.
- Prompt cache reuse across requests with a shared prefix.

If the target laptop turns out to have a large discrete GPU (≥24 GB VRAM), vLLM
becomes attractive for throughput (continuous batching, and XGrammar for structured
output). Keep the provider interface thin enough that this is a config change, and
decide once the hardware is known ([09-open-questions.md](09-open-questions.md) Q1).

**Do not use Ollama as the primary runtime.** It's convenient, but its grammar and
sampler control are weaker and its model-parameter handling is opinionated in ways
that make eval determinism harder. Fine as a fallback for a quick smoke test.

## 2. Model selection

Model IDs are config, not code. The classes and their intent:

| Class | Intended weight | Why |
| ----- | --------------- | --- |
| REASONER | Qwen3-class 30B MoE instruct (~3B active) | Planning, architecture, review. MoE gives 30B-ish quality at ~3B-ish speed — ideal for a laptop |
| CODER | Qwen3-Coder-class 30B MoE | Implementation, refactor, patches |
| CHEAP | Qwen3 4B instruct | Classification, extraction, comprehension probe, Scrum Master |
| JUDGE | REASONER weights, different seed + prompt + context | Independent review without a third resident model |
| EMBED | A small local embedding model (e.g. bge-m3 / nomic-embed class) | Docs retrieval, comprehension-probe similarity |

Notes on the newer Qwen releases you named (3.5 / Coder-Next): treat exact names and
quant availability as a **Phase 0 verification item** — download what's actually
available offline and record the true model IDs in the playbook. Nothing in the
architecture depends on which specific Qwen generation you land on; the class
abstraction exists precisely so this can change.

**Thinking/reasoning modes:** Qwen3 models expose a hybrid thinking mode. Treat it
as a per-role playbook knob (`thinking: on|off`) and *sweep it in the eval*. Expect
thinking-on to help the Architect and Reviewer and to be a waste of tokens for
extraction-shaped roles. Don't assume — measure; it's a cheap sweep with a large
token-cost delta.

## 3. Quantisation and memory budget

Rough planning numbers for a 30B-A3B MoE at various quants (weights only; add KV
cache and runtime overhead):

| Quant | Weights | Quality note |
| ----- | ------- | ------------ |
| Q8_0 | ~32 GB | Reference; use for calibration runs if RAM allows |
| Q6_K | ~25 GB | Near-lossless |
| Q5_K_M | ~21 GB | Good default if it fits |
| Q4_K_M | ~18 GB | **Recommended default**; best quality/size knee |
| IQ4_XS | ~16 GB | When memory-constrained |
| Q3_K_M | ~14 GB | Noticeable degradation on code; avoid for CODER |

KV cache: quantise to `q8_0` for both K and V (`--cache-type-k q8_0 --cache-type-v
q8_0`). At 32k context this saves several GB with minimal quality loss, and context
length is the thing you'll want to spend memory on.

**Run a quantisation sweep as a first-class eval experiment.** `accept_rate` vs
quant level on the smoke suite, on your actual hardware, is a 1-day experiment that
prevents months of guessing. It is entirely plausible that Q5_K_M CODER + Q4_K_M
REASONER is the right split, or that a smaller model with best-of-N=4 beats a
bigger model with N=1 at equal wall-clock. That last comparison is worth running
explicitly — it's the clearest test of the whole "System 2 beats bigger weights"
thesis.

## 4. Routing, queueing, and swap policy

Model swaps dominate latency on a laptop (tens of seconds to load 18 GB from disk,
much worse from a cold page cache). The router therefore:

1. Maintains a **priority queue per model class**, not per request.
2. Uses a **swap-aware scheduler**: drain all queued work for the resident model
   before swapping, subject to a starvation guard (max wait per request).
3. Keeps CHEAP + EMBED **permanently resident** (a few GB total) so probes,
   classification, and retrieval never trigger a swap.
4. Exposes swap count and swap time as first-class metrics — `swaps_per_task` is a
   real cost driver in overnight runs and a legitimate reason to reshape the state
   machine (e.g. batching all reviews across stories into one CODER→JUDGE swap).

This is why the orchestrator's scheduler is swap-aware
([01-architecture.md](01-architecture.md) §4): the right overnight schedule
processes stories in *state-major* order, not story-major order, when swaps are
expensive.

## 5. Prompt cache discipline

llama.cpp reuses the KV cache for a common prefix. Since the retry ladder re-invokes
the same role with mostly the same context, this is a large, easy win — but only if
prompts are laid out for it:

```
[ STABLE PREFIX — identical across attempts, cache hit ]
  role system prompt
  tool definitions
  domain playbook excerpt
  target env contract
  architect contract slice
[ VOLATILE SUFFIX — changes per attempt, recomputed ]
  prior attempt summary
  gate failure evidence (verbatim)
  the specific ask
```

Rules: never interpolate timestamps, attempt counters, or story IDs into the stable
prefix. Sort any collection rendered into the prefix deterministically. Add a
regression test that asserts prefix stability across attempts — it will silently
break otherwise, and you'll only notice as a mysterious 3× slowdown.

## 6. Structured output

Generate GBNF from each artifact's pydantic JSON Schema at startup, cache by schema
hash. Practical guidance:

- Keep schemas **shallow and flat**. Deeply nested grammars degrade small-model
  output quality and generation speed. Prefer several small artifacts over one
  large nested one.
- Constrain enums tightly (`severity: blocker|major|minor|nit`) — free correctness.
- For free-text fields inside a structured artifact, bound the length in the
  grammar. Unbounded free text inside a grammar is where repetition loops happen.
- Always set a `max_tokens` and detect truncation explicitly; a truncated
  grammar-constrained response is invalid JSON and must be retried with a
  `DECODE_FAILURE` event, not silently dropped.
- Retry budget for decode failures is separate from the ladder — a grammar failure
  is a runtime problem, not a reasoning problem.

## 7. Air-gapped supply chain

Everything must be seeded once, from a machine with network, then work forever
offline. Build a `bootstrap/` directory and a `make seed` target that assembles:

| Item | How |
| ---- | --- |
| Model weights | GGUF files + a manifest with sha256, in `models/` |
| Python deps | `uv pip download` into a local wheelhouse; `uv` configured with `--offline --find-links` |
| System packages | A local apt mirror snapshot or a prebuilt base image |
| Container images | `podman save` → tarballs → `podman load` on the laptop; includes the target-env images |
| Docs corpus | cppreference HTML dump, Python docs, man pages, glibc docs, project headers → indexed |
| Eval fixtures | Seed repos as git bundles; Juliet/SARD subset; crackme binaries |
| RE/VR tooling | Ghidra, rizin, capa rules, semgrep rulepacks, AFL++, angr — all vendored |
| Advisory DB | An offline snapshot of a vulnerability DB for dependency checks |

Two rules that save pain later:

1. **Verify offline operation in CI for the project itself.** A test that runs the
   whole bootstrap in a `--network=none` container. Otherwise you'll discover a
   hidden network dependency at 2am on a plane.
2. **Pin and hash everything.** The morning report should be able to state exactly
   which weights, rulepacks, and toolchain produced the result.

## 8. Docs retrieval index

Small models hallucinate APIs constantly; grounding is cheaper than gating alone.

- Hybrid retrieval: BM25 (rank_bm25 or SQLite FTS5) + dense embeddings, reciprocal
  rank fusion. Pure dense retrieval underperforms on exact symbol names, which is
  most of what we look up.
- Chunk by semantic unit (one function/class/section per chunk) with the fully
  qualified symbol name in the chunk header.
- Index: language stdlib docs, third-party lib docs actually vendored in the
  project, the project's own headers/docstrings, man pages, and — importantly —
  **the project's own ADRs and Contracts**, so agents can retrieve prior decisions.
- The `docs_search` tool returns ≤3 chunks with source attribution, and the
  attribution appears in the artifact when the agent relies on it.

Belt and braces: retrieval reduces hallucination, `G-GREEN-5` (LSP symbol
resolution) eliminates it. Do both.
