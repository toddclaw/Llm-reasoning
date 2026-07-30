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

**A1. lets say it is more of a portable data center.  I will have a rack of H200s
running Qwen3.5-397B-A17B-FP8 and Qwen3-Coder-Next-FP8. the laptop will run the AI
front end and the conpile and test. 


**Q2. Target environment(s).** What does "verified to work in the target
environment" mean concretely — a Linux container? a specific distro/glibc? an
embedded or cross-compiled target? multiple targets? Is a container a faithful
proxy, or is a VM required?
This determines the shape of `TargetEnvironment`, whether the sandbox needs
qemu-user/cross toolchains, and how heavy G-INTEGRATE-1/2 are.

**A2.  the target environment is running on a proxmox server
with a set of virtual nodes inside Qemu with virthual networking
and without access back out to the laptop.  The target environment
will be running the software under evaluation for RE and VR.  Access
from the laptop to the target environment will be through an ssh tunnel
on a given port. 

**Q3. First vertical slice.** Which domain proves the thesis first? The plan
assumes Python (best tooling, fastest loop, cheapest mutation testing), with C++
in Phase 4. If your real near-term work is C++ or RE-heavy, the phase order should
change — at the cost of a slower Phase 1–3 iteration loop.

**A3. Forward development with Python is perfect for the firet vertical slice. 
The RE will be targeting a combination of C and C++.

**Q4. Autonomy and safety posture.** Should unattended runs be allowed to execute
untrusted binaries (RE/VR), and is local-integration-branch-only (never push,
never touch remotes) the right default? Any directories or repos that must be
strictly off-limits?

**A4.  I want the AI agents to run from inside a podman or docker container
so they only have access to the volume mounted at start. I expect the agents to 
write, compule, and run binaries/scripts on the laptop and in the target environment. 
I also expect the agents to use a test harness and write lots of unit/integration/system
tests.  I will be using a git repo and I will not give the podman container
access to the ssh keys, so it will not be able to push. i do expect the agents to create commits. 

## Important — these change scope or effort

**Q5. Greenfield or existing codebases?** Is the primary use "build me this new
tool" or "extend/maintain this existing repo"? Existing repos need repo-comprehension
work (codebase indexing, convention inference, careful blast-radius control) that
greenfield doesn't. If it's mostly existing repos, add a `Codebase Cartographer`
step before `SHAPED`.

**A5.  almost all of the work will be on existing codebases. please follow your suggestion here. 

**Q6. How much of the target work is analysis vs building?** If RE/vuln research is
the majority of your real workload rather than a secondary domain, Phase 5 should
move earlier and the artifact model should be centred on `AnalysisReport` /
`VulnFinding` rather than `Patch`. The scrum roster fits build work better than
analysis work; analysis work may want a different roster (analyst, verifier,
reporter) sharing the same harness.

**A6.  there will be two distinct but related paths of work. in tge RE/VR path,
i will be asking questions to understand the system under evaluation.  in this path
i need to ensure all conclusions are backed up with data and can be verified from the
data provided in the answers. the other path will be forward development of tools to interact with
the system under evaluation and will initially be in Python and then transition to C/C++.  Would it be possible
to tell the agents up front through either the interface or through which script i use to start:
with path we are using in each session?

 
**Q7. Scale of a "night's work".** Is the typical overnight ask one medium feature,
or a whole backlog of ten stories? This sets scheduler complexity and whether epic
decomposition needs to be strong from Phase 2 or can wait.

**A7. initially id like to test conpletion of one medium feature. if this effort is 
successful with that, i will need to expand out to epics. likely i will also
want to give the agents a big backlog of work that may take 2-10 dats to complete. But this
will only work if i can trust tge medium tasks.

**Q8. Existing assets.** Do you have codebases, test suites, past failed attempts,
or known-hard tasks that should seed the eval suite? Real tasks from your own work
are worth ten synthetic ones. Also: do you already have specific Qwen GGUFs
downloaded, and at what quant?

**A8.  for now i need to work with synthetic tests. i will give additional feedback on the types as we go along.
i gave some details on the AI models above. 

**Q9. Hard-gate calibration.** The defaults proposed are strict (mutation ≥75%,
diff branch coverage ≥90%, zero `major` review findings, zero new lint
suppressions). Strict gates mean higher quality and more parked stories. Do you
want to start strict and relax, or start moderate and tighten? (Recommendation:
start strict — it's much easier to notice a system that parks too much than one
that ships plausible garbage.)

**A9.  Start strict. my coding standards are quite high and i need the results to be 
at a high professional software development level. i am an r&d researcher with 
3 decades of experience and the products i release need to work correctly, have a good architecture,
be well tested, have good documentation, have good CI/CD, and high quality UX. 

**Q10. Human-in-the-loop touchpoints.** Truly zero-touch overnight, or is a morning
review-and-answer cycle acceptable where you unblock parked stories and the system
picks them up the next night? The latter is dramatically more effective, and
suggests building a lightweight "answer the parked questions" CLI early.

**A10.  the latter. 

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

## New — arising from your answers (A1/A2/A4/A6)

**Q16. Rack sizing.** How many H200s, and how are they grouped? This sets the
tensor-parallel degree for the 397B model, how many concurrent sequences vLLM can
serve, and the KV budget at 128k context — which in turn sets how wide best-of-N and
self-consistency can go. (Not blocking for Phase 0; needed to tune Phase 2 onward.)

**Q17. Where do the gate runners run?** A1 says the laptop runs "compile and test",
but the resource inversion ([05](05-inference-and-topology.md) §4) makes compile/
test/mutation the new bottleneck. Options: (a) laptop only; (b) a dedicated
build/test VM on the Proxmox host; (c) spare rack CPU. Recommendation: put the
BUILD-path gate runners on a Proxmox build VM so the laptop stays a thin front end
and mutation/fuzzing can scale — but the target-env *demo* (G-DEMO-*) must still run
in the isolated target VM, not the build VM. Does that split match your setup?

**Q18. Tunnel + VM lifecycle.** Are the Proxmox target VMs long-lived, or spun from
a golden snapshot per run/per story (cleaner provenance, better isolation for
detonation)? And is the single forwarded SSH port stable, or negotiated per run? The
remote runner's design depends on this.

**Q19. INVESTIGATE authorisation.** For RE/VR, what defines "authorised scope" in
`scope.yaml` in practice — specific VM IDs, binary hashes, a network range? The
Analyst's tools hard-refuse outside it, so the schema needs to match how you think
about targets.

**Q20. Cross-path handoff.** When an INVESTIGATE run produces a `Finding` ("the
target parses length-prefixed frames, no bounds check at offset X"), do you want the
system to *offer* to seed a BUILD story from it automatically, or keep the two paths
strictly manual with you as the bridge? (Recommendation: offer, never auto-start.)
