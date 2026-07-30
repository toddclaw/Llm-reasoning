# 09 — Open Questions

Grouped by how much they change the plan. Q1–Q4 are asked interactively; the rest
are here so nothing is lost.

## Blocking — these change the architecture

**Q1. Laptop hardware.** RAM, GPU + VRAM, CPU cores, disk, OS.
This determines: which quant, how many resident models, whether "different model
per agent" is literal or via seed/prompt/LoRA differentiation, whether vLLM is an
option, best-of-N width, and every budget number in
[07-overnight-autonomy.md](07-overnight-autonomy.md). Everything downstream is
sized off this.

**Q2. Target environment(s).** What does "verified to work in the target
environment" mean concretely — a Linux container? a specific distro/glibc? an
embedded or cross-compiled target? multiple targets? Is a container a faithful
proxy, or is a VM required?
This determines the shape of `TargetEnvironment`, whether the sandbox needs
qemu-user/cross toolchains, and how heavy G-INTEGRATE-1/2 are.

**Q3. First vertical slice.** Which domain proves the thesis first? The plan
assumes Python (best tooling, fastest loop, cheapest mutation testing), with C++
in Phase 4. If your real near-term work is C++ or RE-heavy, the phase order should
change — at the cost of a slower Phase 1–3 iteration loop.

**Q4. Autonomy and safety posture.** Should unattended runs be allowed to execute
untrusted binaries (RE/VR), and is local-integration-branch-only (never push,
never touch remotes) the right default? Any directories or repos that must be
strictly off-limits?

## Important — these change scope or effort

**Q5. Greenfield or existing codebases?** Is the primary use "build me this new
tool" or "extend/maintain this existing repo"? Existing repos need repo-comprehension
work (codebase indexing, convention inference, careful blast-radius control) that
greenfield doesn't. If it's mostly existing repos, add a `Codebase Cartographer`
step before `SHAPED`.

**Q6. How much of the target work is analysis vs building?** If RE/vuln research is
the majority of your real workload rather than a secondary domain, Phase 5 should
move earlier and the artifact model should be centred on `AnalysisReport` /
`VulnFinding` rather than `Patch`. The scrum roster fits build work better than
analysis work; analysis work may want a different roster (analyst, verifier,
reporter) sharing the same harness.

**Q7. Scale of a "night's work".** Is the typical overnight ask one medium feature,
or a whole backlog of ten stories? This sets scheduler complexity and whether epic
decomposition needs to be strong from Phase 2 or can wait.

**Q8. Existing assets.** Do you have codebases, test suites, past failed attempts,
or known-hard tasks that should seed the eval suite? Real tasks from your own work
are worth ten synthetic ones. Also: do you already have specific Qwen GGUFs
downloaded, and at what quant?

**Q9. Hard-gate calibration.** The defaults proposed are strict (mutation ≥75%,
diff branch coverage ≥90%, zero `major` review findings, zero new lint
suppressions). Strict gates mean higher quality and more parked stories. Do you
want to start strict and relax, or start moderate and tighten? (Recommendation:
start strict — it's much easier to notice a system that parks too much than one
that ships plausible garbage.)

**Q10. Human-in-the-loop touchpoints.** Truly zero-touch overnight, or is a morning
review-and-answer cycle acceptable where you unblock parked stories and the system
picks them up the next night? The latter is dramatically more effective, and
suggests building a lightweight "answer the parked questions" CLI early.

## Deferred — decide later, cheap to change

**Q11.** Should Nightshift expose an MCP interface so Claude Code can drive it (and
so you can compare a frontier orchestrator against the local one on the same
harness)? Nice ablation, not needed early.

**Q12.** Multi-repo / monorepo support, or one project at a time?

**Q13.** Do you want a live TUI showing story states during a run, or is the morning
report enough? (A `--watch` TUI is genuinely useful during Phase 2–3 debugging.)

**Q14.** Naming. "Nightshift" is a working name.

**Q15.** Where does documentation live for *your* projects — in-repo Markdown only,
or a docs site generator (Sphinx/Doxygen/mkdocs) that G-DOC-* should also build and
link-check?
