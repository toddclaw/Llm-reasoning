# 05 — Inference, Topology, and the Offline Supply Chain

Revised after A1/A2/A4. This is no longer a single-laptop design.

## 1. Physical topology

```
┌───────────────────────────────────────────────────────────────────────┐
│ AGENT CONTAINER  (podman, rootless)                                   │
│   nightshift orchestrator, agents, tool layer, gate LOGIC (pure)      │
│   mounts: /work (project volume, rw), docs corpus (ro)                │
│   NO ssh keys.  NO host fs beyond the mount.  NO oracle mounts.       │
│   egress allowlist:  rack:8000 (vLLM)  +  host:PORT (tunnels)         │
└──────────┬─────────────────────────────────┬──────────────────────────┘
           │ LAN / https                     │ localhost:PORTs
           ▼                                 ▼
┌────────────────────────┐        ┌──────────────────────────────────────┐
│ H200 RACK              │        │ LAPTOP HOST  (thin front end)        │
│  vLLM: Qwen3.5-397B    │        │  owns ssh keys + tunnels             │
│        -A17B-FP8       │        │  holds attestation key               │
│  vLLM: Qwen3-Coder-    │        │  owns git remote credentials         │
│        Next-FP8        │        │  runs the remote-runner broker only  │
│  + judge / cheap /embed│        └──────────────┬───────────────────────┘
└────────────────────────┘                       │ ssh tunnels (stable ports)
                              ┌──────────────────┴──────────────────┐
                              ▼                                     ▼
              ┌──────────────────────────────┐      ┌──────────────────────────────┐
              │ PROXMOX · BUILD/TEST VM      │      │ PROXMOX · TARGET VM(s)       │
              │  gate runners: compile,      │      │  software under evaluation   │
              │  test, coverage, mutation,   │      │  RE/VR detonation            │
              │  lint, scan, from-scratch    │      │  G-DEMO-* runs HERE          │
              │  build   (A17: option b)     │      │  ✗ no route back to laptop   │
              │  local-net only, no internet │      │  local-net only              │
              └──────────────────────────────┘      └──────────────────────────────┘
```

Four trust tiers (A17 split the runners off the laptop onto a dedicated Proxmox
build/test VM, keeping the laptop a thin front end):

| Tier | Trusts | Holds | Cannot |
| ---- | ------ | ----- | ------ |
| Agent container | nothing | agent code, project volume | reach internet, reach host fs, push to git, ssh anywhere |
| Laptop host | itself | ssh keys, attestation key, git creds | — |
| Build/test VM | the project tree | toolchains, test/mutation/scan runners | reach the internet; reach the target VMs |
| Target VM(s) | nothing | software under evaluation, detonated samples | reach back to the laptop or the build VM |

Two isolation properties the topology gives us for free:

- **The one-way network into the target VMs** makes RE/VR detonation genuinely safe
  in a way seccomp profiles never quite are. The plan leans on it.
- **The build/test VM is separated from the target VM.** Build-time compromise (a
  malicious `Makefile`, a hostile test dependency) cannot reach the software under
  evaluation, and target detonation cannot poison the build. G-DEMO-* deliberately
  runs in the *target* VM, not the build VM, so "it works" is proven where it must
  actually run — never on the machine that built it.

**Evidence flows by pull, and is attested on the host.** Neither the build VM nor
the target VMs can initiate anything toward the laptop. The host-side **remote-runner
broker** invokes over a stable tunnel (A18), captures `stdout/exit/artifacts`, and
**attests them on the host** with a key that never leaves it. So even though the
runners now live on the build VM, a `Record`'s provenance is still minted in the one
tier that holds the key — the build VM produces *output*, the host turns output into
*attested evidence*. P3 holds across all four tiers.

**Stable tunnels and stable VMs (A18).** For these experiments the SSH tunnel and the
QEMU nodes are long-lived and stably addressed, which simplifies the remote runner
(no per-run port negotiation, no snapshot-spin lifecycle). The tradeoff is that
long-lived VMs don't give fresh-per-run isolation, so **every Record captures the
target/build VM identity and a state fingerprint** (VM id + a recorded snapshot/boot
id) for reproducibility. Where a story needs guaranteed-clean state — cold-start
demos (G-DEMO-3), detonation — the runner reverts the VM to a named snapshot first
and records the snapshot id. Moving to spin-per-story snapshots later is a
runner-internal change, not an architecture change.

**Agents never hold SSH.** The tunnels are established by the host before the run and
exposed to the container as forwarded ports. The agent-facing tools are
`run_in_build(cmd)` and `run_in_target(cmd, vm)` — allowlisted per role, routed
through the broker, which is the only component that speaks the transport.

## 2. Inference stack — vLLM, not llama.cpp

The earlier llama.cpp recommendation was sized for a laptop and is now wrong.

**Use vLLM (or SGLang) on the rack.**

- **FP8 is native on Hopper.** H200 executes FP8 in hardware and both named
  checkpoints are already FP8, so there is no quantisation decision and no quality
  sweep to run. That deletes a planned experiment outright.
- **Continuous batching** turns concurrency from a scheduling problem into a
  throughput win. Parallel stories, parallel agents, and wide best-of-N all become
  ordinary rather than exotic.
- **Automatic prefix caching** delivers the retry-ladder cache reuse the prompt
  layout in §5 was designed for — that discipline carries over unchanged.
- **Structured output** via XGrammar / `guided_json` straight from our pydantic JSON
  Schema. P4 survives intact; only the backend name changes.
- Both models stay **resident simultaneously** on separate GPU groups.

Consequences that ripple outward:

- **No model swapping.** Delete swap-aware scheduling, swap batching, the
  `swaps_per_task` metric, and the state-major scheduling contortion in
  [07](07-overnight-autonomy.md) §5.
- **`JUDGE` becomes a genuinely different model** rather than the same weights with
  a different seed — independence of weights *and* context, as originally wanted.
- **Best-of-N moves from ladder rung 3 onto the default path** for implementation.
  See §4 for the catch, which is real.

## 3. Model classes → real bindings

```yaml
model_classes:
  REASONER: { endpoint: rack, model: Qwen3.5-397B-A17B-FP8,  ctx: 128000 }
  CODER:    { endpoint: rack, model: Qwen3-Coder-Next-FP8,   ctx: 128000 }
  JUDGE:    { endpoint: rack, model: Qwen3.5-397B-A17B-FP8,  ctx:  64000 }
  CHEAP:    { endpoint: rack, model: <small Qwen3 instruct>, ctx:  32000 }
  EMBED:    { endpoint: rack, model: <bge-m3 / qwen3-embed>, ctx:   8000 }
```

Sizing: a 397B-parameter MoE at FP8 is roughly 400 GB of weights plus KV cache. On
141 GB H200s that means tensor parallelism across ≥4 GPUs for the large model, with
a second group for the coder. Exact TP degree, max concurrent sequences, and KV
budget depend on the rack size — Q16 in [09](09-open-questions.md). Pin
`--max-model-len` deliberately rather than accepting the checkpoint maximum: KV
cache at 128k × many concurrent sequences is the binding constraint, and long
context is only worth paying for where the eval says it helps.

Keep `REASONER` and `JUDGE` seeds offset, and keep JUDGE blind to the author's
rationale ([02](02-agents.md) §2.5). Context independence still does most of the work
even when weights are shared.

## 4. The resource inversion — the most important consequence

On a laptop, inference was scarce and verification was comparatively cheap. That is
now reversed:

> **Inference is abundant. The build/test VM's throughput is the bottleneck.**

The runners live on a dedicated Proxmox build VM (A17), so the scarce resource is
that VM's CPU, not the laptop's — but the inversion is the same, and scheduling and
budgets flip accordingly:

- **Token budgets stop binding.** Gate-runner wall-clock becomes the scheduled
  resource. Budgets in [07](07-overnight-autonomy.md) are re-expressed in
  gate-runner-minutes; tokens are tracked but rarely limiting.
- **The build VM can be sized/scaled independently.** Because it's a Proxmox VM, more
  vCPUs (or a second build VM behind the broker) is a provisioning decision, not a
  hardware purchase — a real advantage of A17 over laptop-only runners. The broker
  load-balances gate jobs across whatever build VMs exist.
- **Best-of-N has a new cost model.** Generating 8 candidate patches is nearly free;
  *evaluating* 8 through the gate battery costs 8× the scarcest resource. So
  candidates run through a two-stage funnel:

  | Stage | Runs on | Cost | Applied to |
  | ----- | ------- | ---- | ---------- |
  | 1. Static filter — parse, type-check, LSP symbol resolution, lint, AST vacuity | agent container CPU, parallel | seconds | all N candidates |
  | 2. Full battery — unit tests, coverage, mutation, sanitizers, from-scratch build | build VM | minutes | top 1–2 survivors |

  Stage 1 runs in the agent container (it's pure static analysis, no execution) so
  it doesn't consume a scarce build-VM slot; G-GREEN-5 earns its keep twice here — a
  correctness gate *and* a nearly free candidate ranker.
- **Self-consistency is cheap; spend it where verification cannot reach.** For
  decisions no gate can check — architecture choices, story decomposition, RE
  triage calls — sample k times independently and take consensus, surfacing
  disagreement to the Manager. This is the right place to spend the rack's
  abundance, because it substitutes inference for verification we cannot otherwise
  buy. It is also the honest answer to "who checks the Architect", which
  [03](03-verification.md) §5 previously listed as an ungated residual risk.
- **Mutation testing and fuzzing become the dominant wall-clock costs.** Both are
  embarrassingly parallel and run in a low-priority pool on the build VM (fuzzing
  may warrant its own VM so a long campaign never starves interactive gates).

## 5. Prompt cache discipline (unchanged, now worth more)

```
[ STABLE PREFIX — identical across attempts ⇒ cache hit ]
  role system prompt
  tool definitions
  domain playbook excerpt
  target environment contract
  codebase map digest          ← new, large, high cache value
  architect contract slice
[ VOLATILE SUFFIX — recomputed each attempt ]
  prior attempt summary
  gate failure evidence (verbatim)
  the specific ask
```

The codebase map digest ([02](02-agents.md) §2.0) is large and stable across every
story in a repo, which makes prefix caching worth substantially more here than in
the laptop design. Keep the regression test asserting prefix stability across
attempts — never interpolate timestamps, attempt counters, or story IDs above the
volatile line.

## 6. Context budgets — recalibrate, don't abandon

With a frontier-class model and 128k context, the original ≲8k-per-call budgets are
too tight to be optimal and too arbitrary to keep on faith. But "put everything in"
is also wrong: irrelevant context measurably degrades quality, and the tight budgets
were never *only* about model capacity — they enforce the decomposition that makes
gates meaningful in the first place.

Resolution: **context budget becomes a swept parameter per role**, not a principle.
Phase 3 sweeps {8k, 24k, 64k} per role against `accept_rate` and cost. Expect the
answer to differ sharply by role — Cartographer and Architect will want a lot;
`tdd-dev:test` probably still wants very little, because a test author who has read
the implementation writes tests that mirror it.

## 7. Structured output

Same discipline, new backend: pydantic → JSON Schema → `guided_json` (XGrammar).
Keep schemas shallow, enums tight, free-text length-bounded, `max_tokens` always
set, truncation detected explicitly and retried as `DECODE_FAILURE` outside the
reasoning ladder.

One addition now that decoding is fast: on decode failure, retry with a *simplified*
schema (optional fields dropped) before failing the attempt. Cheap robustness that
costs nothing at this inference budget.

## 8. Offline supply chain

"No internet" still holds — it now means *no internet anywhere in the topology*,
with a trusted LAN to the rack. Seeding happens once from a networked machine.

| Item | Destination | Notes |
| ---- | ----------- | ----- |
| Model weights (FP8) | rack | manifest + sha256, recorded in every report |
| Python deps | agent image + build VM | `uv pip download` wheelhouse, `--offline --find-links` |
| Toolchains (gcc/g++/cmake/ninja, test/mutation/scan tools) | **build VM** | this is where compile/test/mutation run (A17) |
| Container images | laptop | `podman save` / `load` tarballs |
| Proxmox VM templates | proxmox host | golden images for build VM and each target env, with named snapshots |
| Docs corpus | agent container (ro) | cppreference, Python docs, man pages, C/C++ standards |
| RE/VR tooling | agent container (static) + target VM templates (dynamic) | Ghidra, rizin, capa rules, semgrep rules, AFL++, angr |
| Advisory DB snapshot | agent container | dependency vulnerability checks |
| Eval fixtures | laptop | seed repos as git bundles; oracles never mounted into the container |

Two rules worth keeping:

1. **Verify offline operation in CI.** Bootstrap the whole system in a
   `--network=none` container as a test. The agent container's egress allowlist
   (rack + tunnel port only) is a security control, so it gets a regression test
   that asserts everything else is unreachable.
2. **Pin and hash everything.** The morning report states exactly which checkpoints,
   rulepacks, VM template snapshots, and toolchains produced the result.

## 9. Docs retrieval index

Unchanged in design — hybrid BM25 + dense with reciprocal rank fusion, chunked by
semantic unit, ≤3 chunks returned with attribution — and now also indexing the
**codebase map and its extracted convention exemplars**, since almost all work is on
existing repositories.

Grounding reduces hallucination; G-GREEN-5 (LSP symbol resolution) eliminates it.
Both still apply. A 397B model hallucinates less often, not never — and "less often"
is precisely the regime where a human stops checking and gets burned.
