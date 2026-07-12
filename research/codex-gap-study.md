# Capability-gap study for a frontier long-horizon software-engineering environment

**Research cutoff:** 12 July 2026  
**Decision:** Proceed to proposal review with **counterevidence-triggered repair revision under an inherited failed fix** as the primary direction. Do not implement it until the capability definition and verifier design are approved.

## Technical summary

- **SOURCE-BACKED FACT — Frontier systems still have separable judgment and recovery failures.** FixedBench reports that current agents make undesirable code changes in 35–65% of already-fixed cases; HiL-Bench reports a large gap between full-information performance and performance when agents must decide when to ask; Precise Debugging Benchmark reports test pass rates above 76% but edit precision below 45%; and debug-gym establishes interactive runtime inspection as a distinct agent setting. [[S14]](#s14) [[S15]](#s15) [[S16]](#s16) [[S18]](#s18)
- **SOURCE-BACKED FACT — “Make the task larger” is not a novel direction.** SWE-Bench Pro, SWE-EVO, RoadmapBench, Terminal-Bench 2.0, and OSWorld 2.0 already cover difficult or long-horizon work. SWE-EVO uses release-sized evolution tasks, and RoadmapBench uses multi-target version-upgrade tasks. [[S5]](#s5) [[S7]](#s7) [[S8]](#s8) [[S9]](#s9) [[S12]](#s12)
- **SOURCE-BACKED FACT — Test-only grading is a material soundness risk.** OpenAI’s July 2026 audit estimates that about 30% of SWE-Bench Pro tasks are broken and identifies overly strict tests, underspecified prompts, low coverage, and misleading prompts. SpecBench separately shows that visible-test success can diverge from held-out compositional behavior. [[S4]](#s4) [[S19]](#s19)
- **INFERENCE — The best one-week prototype is a small, original, deterministic incident-repair world, not a scraped repository benchmark.** Each instance should start from a failed inherited remediation and an incident whose visible symptoms support a plausible but wrong diagnosis. The agent must detect the failed state, preserve or restore a safe checkpoint, obtain counterevidence from heterogeneous artifacts, revise the repair target, make a bounded change, and verify counterfactual workloads. This creates genuine causal length without relying on repository size.
- **INFERENCE — The main verifier should grade canonical end state and hidden counterfactual behavior, not prose about the agent’s hypothesis.** Trajectory checks can establish that required tools and recovery transitions occurred, but they should be secondary because internal belief revision is not directly observable.
- **Primary uncertainty:** no current primary source directly isolates *counterevidence-triggered revision after an inherited failed repair* as its measured construct. That is the novelty opportunity and also the main risk: a prototype may collapse into a smaller ITBench/debug-gym task or into ordinary hidden-test patching.

## Claim labels

- **SOURCE-BACKED FACT:** directly supported by one or more opened primary sources, cited by source ID.
- **INFERENCE:** a synthesis, design judgment, or prediction derived from the sources; not claimed as a published result.
- **OPEN QUESTION:** evidence needed before committing to implementation.
- **UNVERIFIED CLAIM:** encountered but excluded from scoring because a sufficient primary source was not verified. **No unverified claim is used in the recommendation or scores.**

## 1. Research method and search scope

### Decision question

Which specific current weakness of frontier coding or software-engineering agents can support an original, runnable, contamination-resistant RL environment that one engineer can prototype deeply in roughly five to seven focused days, while enforcing at least 15–30 causally linked actions, heterogeneous tools, constraining state transitions, and unavoidable failure detection and recovery?

### Method

1. Read the repository constraints and quality gates before research.
2. Searched for primary papers, benchmark repositories, model/evaluation reports, and official audits, prioritizing work published or substantially updated in 2025–2026.
3. Opened the actual paper page, full HTML paper where available, official repository, or official technical report. Search snippets and third-party summaries were not treated as evidence.
4. Mapped each nearby benchmark to its task unit, interaction model, grading target, and contamination posture.
5. Generated five candidate gaps, including crowded ideas as negative controls.
6. Scored each candidate on the nine requested dimensions using a 1–5 ordinal scale. Scores represent this project’s design judgment, not published measurements.
7. Applied a feasibility filter: a candidate must admit a small original substrate, deterministic oracle, executable verifier, and convincing long-horizon construction without requiring a large corpus or months of manual curation.

### Search scope

The study covered the required families: SWE-bench and Verified, SWE-Bench Pro, SWE-bench Live, SWE-EVO, RoadmapBench, Terminal-Bench 2.0, τ-bench, OSWorld and OSWorld 2.0, SLUMP, FixedBench, and Precise Debugging Benchmark. It also examined debug-gym, ITBench, HiL-Bench, SpecBench (reward hacking), and a recent structured-recovery paper because they are directly adjacent to the proposed construct.

### Boundary conditions

- **SOURCE-BACKED FACT:** SWE-bench asks an agent to generate a patch for a real GitHub issue and grades it in a reproducible container. [[S1]](#s1)
- **SOURCE-BACKED FACT:** OpenAI’s February 2026 audit concluded that SWE-bench Verified no longer provided a clean frontier signal because of test-design defects and contamination; its July 2026 audit subsequently retracted the recommendation to use SWE-Bench Pro after finding widespread task issues there too. [[S3]](#s3) [[S4]](#s4)
- **INFERENCE:** benchmark realism and verifier soundness must be treated as separate axes. Scraped human work can be realistic yet underdetermined; procedurally generated work can be less natural yet more causally and evaluatively controlled.
- **INFERENCE:** “long horizon” is not counted by token budget, changed lines, or repository size alone. The proposed environment must make later valid actions depend on earlier evidence and state transitions.

## 2. Verified primary-source table

Twenty primary sources were opened and used. “Does not establish” is included to prevent evidence from being stretched beyond its design.

| ID | Primary source | Date / status | What it establishes for this study | What it does **not** establish |
|---|---|---|---|---|
| <a id="s1"></a>S1 | [SWE-bench official repository and paper links](https://github.com/swe-bench/SWE-bench) | ICLR 2024; repo inspected 2026-07-12 | Task unit is repository + GitHub issue → patch; Docker evaluation; Verified is a 500-task human-reviewed subset. | It does not isolate decision-making under stale, partially fixed, or operationally changing state. |
| <a id="s2"></a>S2 | [Introducing SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/) | 2024; updated 2025 | Documents expert review, fail-to-pass and pass-to-pass tests, and the motivation for filtering unsolvable or underspecified tasks. | Human review does not guarantee future frontier-level construct validity. |
| <a id="s3"></a>S3 | [Why SWE-bench Verified no longer measures frontier coding capabilities](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/) | 2026-02-23 | In an audited 138-task subset, 59.4% had material issues; reports evidence of benchmark exposure and recommends stopping frontier reporting on Verified. | The audited subset is failure-enriched, not a random estimate of all 500 tasks. |
| <a id="s4"></a>S4 | [Separating signal from noise in coding evaluations](https://openai.com/index/separating-signal-from-noise-coding-evaluations/) | 2026-07-08 | On SWE-Bench Pro public split, automated/agent review flagged 27.4% broken and human review 34.1%; identifies strict tests, underspecification, low coverage, and misleading prompts; retracts the earlier recommendation. | It does not show that synthetic tasks are automatically sound or that all Pro tasks are unusable. |
| <a id="s5"></a>S5 | [SWE-Bench Pro](https://arxiv.org/abs/2509.16941) | 2025 preprint / ICLR 2026 submission | 1,865 tasks across 41 repositories; multi-file, enterprise-oriented issue resolution; public, held-out, and commercial partitions. | Its published paper does not validate the specific hypothesis-revision construct; later audit raises task-quality concerns. |
| <a id="s6"></a>S6 | [SWE-bench Goes Live!](https://arxiv.org/abs/2505.23419) | NeurIPS 2025 | Live-updatable curation; initial 1,319 tasks from 93 repositories; recent issues and per-task containers target freshness and contamination resistance. | Freshness does not by itself make prompts/tests complete or produce stateful operational recovery. |
| <a id="s7"></a>S7 | [SWE-EVO](https://arxiv.org/abs/2512.18470) | 2025, revised 2026 | 48 release-sized evolution tasks from seven Python projects, averaging 21 files and 874 tests; introduces a partial-progress Fix Rate. | It does not require an agent to revise a falsified diagnosis or recover an inherited failed repair. |
| <a id="s8"></a>S8 | [RoadmapBench](https://arxiv.org/abs/2605.15846) | 2026 preprint | 115 multi-target version-upgrade tasks across 17 repositories and five languages; median gold change of 3,700 lines across 51 files. | Scale of change is not proof of heterogeneous operational tools or recovery transitions. |
| <a id="s9"></a>S9 | [Terminal-Bench 2.0](https://arxiv.org/abs/2601.11868) | 2026 preprint | 89 hard terminal tasks, each with a unique environment, human solution, and comprehensive tests; frontier systems scored below 65% in the paper. | It is broad across terminal workflows and does not isolate a single debugging decision construct. |
| <a id="s10"></a>S10 | [τ-bench](https://arxiv.org/abs/2406.12045) | 2024 preprint | Dynamic user-agent-tool interaction with policy rules; final database state grading; pass^k measures repeated-run reliability. | Retail/airline API workflows do not measure code/config/log/trace diagnosis or patch quality. |
| <a id="s11"></a>S11 | [OSWorld](https://arxiv.org/abs/2404.07972) | 2024 preprint | Real executable computer environments spanning applications and interfaces; execution-based evaluation permits alternative action sequences. | The original benchmark is not specialized for software incident repair or causal fault oracles. |
| <a id="s12"></a>S12 | [OSWorld 2.0](https://arxiv.org/abs/2606.29537) | 2026 preprint | 108 professional long-horizon workflows; targets dynamic environments, cross-source reasoning, implicit-state inference, and skipped verification; reports 20.6% best binary completion at 500 steps. | GUI/professional workflow completion does not isolate debugging-hypothesis revision or code repair. |
| <a id="s13"></a>S13 | [When the Specification Emerges (SLUMP)](https://arxiv.org/abs/2603.17104) | 2026 preprint | ~60 progressively disclosed requests over 20 research-coding targets; finds lower faithfulness than single-shot controls and evaluates a state-tracking mitigation. | It studies commitment tracking under emergent specification, not runtime falsification of a causal repair hypothesis. |
| <a id="s14"></a>S14 | [Coding Agents Don’t Know When to Act (FixedBench)](https://arxiv.org/abs/2605.07769) | 2026 preprint / workshop | 200 already-fixed tasks; agents make undesirable changes in 35–65% of cases; explicit abstention framing can cause over-abstention on partially fixed tasks. | It is primarily a fix-versus-abstain inversion and does not enforce a 15–30 action operational recovery sequence. |
| <a id="s15"></a>S15 | [Precise Debugging Benchmark](https://arxiv.org/abs/2604.17338) | 2026 preprint | Automatically composes verified atomic bugs; measures edit precision and bug recall; reports >76% test pass but <45% precision for named frontier models. | Mostly generated program repair does not itself cover heterogeneous runtime artifacts, rollback, or incident state. |
| <a id="s16"></a>S16 | [debug-gym](https://arxiv.org/abs/2503.21557) and [official repository](https://github.com/microsoft/debug-gym) | 2025 preprint / open source | Defines an interactive text environment with debugger and code tools; observations change after each action; integrates existing repair datasets. | It provides an environment and baselines but does not define counterevidence-triggered revision as a scored construct. |
| <a id="s17"></a>S17 | [ITBench](https://arxiv.org/abs/2502.05352) and [official repository](https://github.com/itbench-hub/ITBench) | ICML 2025 / open source | 94 IT automation scenarios across SRE, CISO, and FinOps; paper reports 13.8% SRE resolution; real Kubernetes-style incident environments are close to operational diagnosis. | Its broad task-completion score does not isolate inherited-repair rollback plus falsified-hypothesis revision; the full infrastructure is heavier than a one-week original prototype. |
| <a id="s18"></a>S18 | [HiL-Bench](https://arxiv.org/abs/2604.09408) | 2026 preprint | 300 SWE/SQL tasks with progressively discovered blockers; Ask-F1 balances precise asking and blocker recall; best reported tool-enabled SWE pass@3 is 12% versus 64–88% with full information. | Asking for missing requirements is not the same as revising a diagnosis from machine-generated runtime evidence. |
| <a id="s19"></a>S19 | [SpecBench: Measuring Reward Hacking in Long-Horizon Coding Agents](https://arxiv.org/abs/2605.21384) | 2026 preprint | Separates visible feature tests from held-out compositional tests; reports persistent gaps and compositional failures as the dominant qualitative category. | Its tasks focus on implementation against a specification, not incident recovery or inherited faulty state. |
| <a id="s20"></a>S20 | [Debugging the Debuggers: Failure-Anchored Structured Recovery](https://arxiv.org/abs/2605.08717) | 2026 preprint | Structures failed-run telemetry into evidence, diagnosis, and bounded recovery guidance; reports a diagnosis–recovery gap over 257 initially unresolved cases. | It evaluates a recovery framework, not an original RL environment that procedurally forces hypothesis revision and grades canonical end state. |

## 3. Candidate analyses

### Candidate 1 — Counterevidence-triggered repair revision under an inherited failed fix

**Verdict: GO, subject to a verifier spike before environment implementation.**

1. **Capability name.** Counterevidence-triggered repair revision under an inherited failed fix.
2. **Exact expected model failure.** The agent anchors on a plausible diagnosis supplied by the ticket or embodied in the inherited patch. When logs, traces, state snapshots, or canary behavior contradict that diagnosis, it layers another patch onto the same theory, suppresses the symptom, or declares success after a narrow check instead of restoring a safe checkpoint and changing the causal target.
3. **Primary sources.** debug-gym establishes interactive information gathering; Precise Debugging Benchmark establishes high functional success with low edit precision; FixedBench establishes action bias and an abstention/over-abstention tradeoff; ITBench establishes low success in operational IT scenarios; PROBE reports a diagnosis–recovery gap. [[S14]](#s14) [[S15]](#s15) [[S16]](#s16) [[S17]](#s17) [[S20]](#s20)
4. **What the sources actually prove.** **SOURCE-BACKED FACT:** the cited works separately show that current agents over-edit, act when no edit is needed, benefit from or can be studied with interactive runtime tools, struggle on operational scenarios, and do not automatically turn a correct diagnosis into successful recovery. [[S14]](#s14) [[S15]](#s15) [[S16]](#s16) [[S17]](#s17) [[S20]](#s20)
5. **What they do not prove.** **OPEN QUESTION:** none of the sources directly measures whether a frontier agent will retract an inherited causal theory after machine-observable counterevidence while preserving rollback options. The proposed construct is a synthesis, not a quoted benchmark finding.
6. **Why users care.** **INFERENCE:** real maintainers often inherit tickets, partial fixes, canaries, and incident narratives from earlier actors. An agent that can write a patch but cannot recognize that the current repair path is wrong increases mean time to recovery and change risk.
7. **Why frontier labs care.** **INFERENCE:** this construct separates code generation from sequential belief updating, calibrated intervention, tool selection, and recovery. It supplies dense but objective signals for post-training: safe checkpoint restored, discriminating evidence collected, correct causal layer repaired, invariants preserved, and counterfactual workloads passed.
8. **Closest existing benchmarks.** ITBench is closest operationally; debug-gym is closest interactively; Precise Debugging Benchmark is closest on targeted editing; FixedBench is closest on deciding not to continue a bad action; SWE-bench variants are closest on executable repository repair. [[S1]](#s1) [[S14]](#s14) [[S15]](#s15) [[S16]](#s16) [[S17]](#s17)
9. **Exact novelty argument.** **INFERENCE:** the proposed task begins *after another repair attempt has already changed the system*. Success requires detecting that inherited failure, restoring a safe state, obtaining evidence that distinguishes two causally plausible explanations, and repairing a different layer. Nearby benchmarks generally begin from a single faulty snapshot and score final task completion; they do not make an earlier failed remediation and its shrinking option set the central construct. The novelty claim must remain this narrow.
10. **Possible task substrate.** An original local service simulator with three to five small components, a SQLite-backed event/state store, versioned code and configuration, deterministic request replays, a canary controller, and separate tools for repository inspection, log search, trace querying, state inspection, deploy/rollback, and workload execution. No external cluster is required.
11. **Ground truth and verifier.** A seed generates a causal graph, one latent fault, one plausible decoy explanation, an inherited patch or configuration change, expected state invariants, visible workloads, and hidden counterfactual workloads. The verifier reads a privileged oracle unavailable to the agent and scores: safe-state restoration, incident resolution, regression invariants, state/data integrity, forbidden-action violations, bounded patch surface, and hidden workload behavior. It ignores the agent’s self-reported diagnosis. A trajectory receipt confirms required state transitions and tool families but contributes only limited auxiliary reward.
12. **Contamination argument.** All component names, dependency graphs, fault locations, event sequences, identifiers, and workloads are newly generated from held-out namespaced seeds. The generator and oracle are excluded from the agent runtime. Even if the task family becomes public, evaluation seeds create unseen causal combinations. This is stronger than relying solely on the recency of public GitHub issues. [[S3]](#s3) [[S4]](#s4) [[S6]](#s6)
13. **Enforcing all four long-horizon requirements.** (a) **15–30+ linked actions:** start from a failed canary and require baseline capture, rollback, reproduction, evidence collection across at least two artifacts, bounded repair, redeploy, and multi-workload verification; the gold trajectory should demonstrate the lower bound. (b) **Heterogeneous tools:** code search/edit, version control, logs, traces, database/state inspector, deployment controller, and workload runner expose non-interchangeable information. (c) **Constraining transitions:** the canary consumes a deployment slot; rollback restores an earlier schema/config snapshot; some traces exist only for replayed requests; deployment revisions determine which artifacts later queries can observe. (d) **Unavoidable failure detection and recovery:** every instance starts with an inherited failed remediation already active, so even the gold solver must detect and recover from failure.
14. **Familiar shortcut or reward hack.** Revert everything, add retries or exception swallowing, hard-code visible request IDs, disable the failing feature, mutate tests, edit the state database directly, or leave the service on the old version. These can clear a visible symptom while violating hidden availability, data, or feature invariants.
15. **Difficulty by construction.** The visible replay supports both the decoy and true cause. A familiar symptom-suppression patch passes the visible smoke check. Hidden tests vary concurrency, request identity, or state history and expose whether the repair addresses the generated causal fault. A second hidden check verifies that rollback and redeploy did not lose committed data or disable required behavior.
16. **Build complexity.** **INFERENCE:** medium. A deep prototype can use one language, one process supervisor, SQLite, and a deterministic event clock. Five to seven days is credible for one task family, 12–20 seeds, verifier tests, a gold solver, and cheat controls; it is not credible for a realistic Kubernetes clone.
17. **Biggest soundness risk.** A task may accidentally allow the agent to identify the correct file directly from generated structure or pass hidden workloads with a broad workaround. Another risk is over-scoring the prescribed trajectory rather than valid alternative recoveries.
18. **Strongest argument against building it.** ITBench plus debug-gym may already cover most of the practical capability, making this an elaborate task-format variation. If the inherited failure and counterevidence do not alter what a rational solver must do, the benchmark would only be ordinary debugging with extra ceremony.
19. **GO / HOLD / REJECT.** **GO** only if a paper-design review can produce two structurally different gold solutions, each requiring recovery and each passing an implementation-agnostic final-state verifier, while a symptom-suppression baseline passes visible checks and fails hidden counterfactual checks.

### Candidate 2 — Evidence-calibrated action selection across stale, partial, and active issues

**Verdict: GO as first fallback.**

1. **Capability name.** Evidence-calibrated selection among inspect, patch, abstain, escalate, roll back, and close-resolved outcomes.
2. **Exact expected model failure.** The agent treats a ticket as an instruction to edit. It patches already-correct code, abstains on a partial fix after being warned about action bias, asks broad questions without inspecting available evidence, or rolls forward when rollback is the only safe action.
3. **Primary sources.** FixedBench directly measures action bias; HiL-Bench directly measures selective escalation; τ-bench measures policy-following tool interaction; OSWorld 2.0 reports guessing instead of asking and skipped verification in long workflows. [[S10]](#s10) [[S12]](#s12) [[S14]](#s14) [[S18]](#s18)
4. **What the sources prove.** **SOURCE-BACKED FACT:** agents often edit already-fixed code; explicit abstention prompts can induce over-abstention on partially fixed cases; progressively discovered blockers create a large help-seeking performance gap; stateful tool environments can grade final database state. [[S10]](#s10) [[S14]](#s14) [[S18]](#s18)
5. **What they do not prove.** The sources do not show that one benchmark combining six maintenance outcomes is better than separate focused benchmarks, nor that action selection alone requires a genuine long horizon.
6. **Why users care.** **INFERENCE:** autonomous issue queues contain duplicates, stale reports, regressions, incomplete fixes, and missing authority. Incorrect action choice creates review load even when the generated code is locally correct.
7. **Why frontier labs care.** **INFERENCE:** the task creates verifiable rewards for selective autonomy rather than unconditional completion and can train both action bias and inaction bias without relying on an LLM judge for the final outcome.
8. **Closest benchmarks.** FixedBench and HiL-Bench are extremely close; τ-bench contributes final-state policy evaluation; SWE-bench supplies the issue-to-patch baseline. [[S1]](#s1) [[S10]](#s10) [[S14]](#s14) [[S18]](#s18)
9. **Exact novelty argument.** **INFERENCE:** FixedBench’s primary contrast is already-fixed versus edit; HiL-Bench’s is ask versus proceed when blockers exist. The proposed environment creates a latent *maintenance state* with multiple valid terminal actions, including rollback and close-resolved, discovered through code history, runtime evidence, and authorization boundaries. Novelty is only defensible if those outcomes share indistinguishable early evidence and require different later actions.
10. **Possible substrate.** A generated repository with a short commit graph, issue text, release metadata, test runner, runtime snapshot, and a deterministic “maintainer” tool that answers only precise questions mapped to seeded blockers.
11. **Ground truth and verifier.** The seed labels the latent case as stale, fully fixed, partially fixed, active fault, unsafe deployment, or unresolvable-without-authority. Canonical end-state assertions check repository diff, deployment revision, issue status, state invariants, and whether escalation used the minimal sufficient question. Ask scoring can adapt HiL-Bench’s precision/recall idea, but final software state remains authoritative. [[S18]](#s18)
12. **Contamination argument.** Generated commit DAGs, issue descriptions, bug states, and answers are original. Evaluation mixes unseen state combinations and vocabulary. No public gold patch exists.
13. **Long-horizon enforcement.** (a) The evidence needed to classify the case is split across history, tests, logs, and current runtime. (b) Git, test, log, deployment, and ask tools are non-interchangeable. (c) Patching changes later test evidence; rollback changes available logs; escalation may reveal exactly one missing fact. (d) Every instance includes either an inherited failing state or a deliberately failing reproduction that must be detected and resolved, though already-fixed cases risk being shorter.
14. **Shortcut / reward hack.** Always escalate; always abstain; make a harmless documentation-only diff; close the issue without verifying runtime; or ask a compound question that lists all possibilities.
15. **Difficulty by construction.** Pair tasks share identical issue text but differ in commit history, deployment revision, or one runtime invariant. A policy keyed on wording fails. Visible tests can pass in both fully and partially fixed cases; hidden state checks distinguish them.
16. **Build complexity.** Medium-low. The latent case generator and final-state verifier are simpler than Candidate 1, but robustly scoring precise escalation and proving a 15–30 action minimum are harder than they appear.
17. **Biggest soundness risk.** The benchmark may measure prompt framing or tool-protocol compliance more than software-engineering judgment, echoing FixedBench’s sensitivity to instructions. [[S14]](#s14)
18. **Strongest argument against.** FixedBench and HiL-Bench together already occupy most of the conceptual territory. Combining them may be less scientifically clean than contributing a targeted extension to either construct.
19. **Verdict.** **GO as fallback**, but only if the task distribution prevents trivial always-ask/always-abstain policies and median gold trajectories exceed 15 causally necessary actions.

### Candidate 3 — Cross-artifact causal repair with compositional invariant preservation

**Verdict: HOLD as second fallback.**

1. **Capability name.** Cross-artifact causal localization and bounded repair across code, configuration, schema/data, logs, and traces while preserving composed invariants.
2. **Exact expected model failure.** The agent finds a locally plausible code fix and stops when unit tests pass, ignoring that the true fault crosses an interface boundary or that its broad change violates a configuration, data, concurrency, or compatibility invariant.
3. **Primary sources.** ITBench shows low SRE task resolution in live IT environments; Precise Debugging Benchmark shows low edit precision despite passing tests; SpecBench shows visible/hidden compositional gaps; SWE-EVO shows regression-heavy multi-file evolution remains difficult. [[S7]](#s7) [[S15]](#s15) [[S17]](#s17) [[S19]](#s19)
4. **What the sources prove.** **SOURCE-BACKED FACT:** current agents struggle on SRE scenarios, over-edit even when functionally correct, and can saturate visible feature tests while failing held-out feature compositions. [[S15]](#s15) [[S17]](#s17) [[S19]](#s19)
5. **What they do not prove.** They do not demonstrate that “cross-artifact” is a unitary model capability rather than the sum of retrieval, domain knowledge, test quality, and patching skill.
6. **Why users care.** **INFERENCE:** production failures routinely manifest in one artifact and originate in another; a code-only repair can corrupt state or leave the operational cause untouched.
7. **Why labs care.** **INFERENCE:** a generated causal graph can provide exact fault provenance and dense, independent objectives without using a reference diff as the only oracle.
8. **Closest benchmarks.** ITBench for operational artifacts, SWE-bench families for repository repair, Precise Debugging Benchmark for bounded edits, and SpecBench for held-out composition. [[S1]](#s1) [[S15]](#s15) [[S17]](#s17) [[S19]](#s19)
9. **Exact novelty argument.** The proposed unit of evaluation is a generated *causal interface violation* whose manifestations are deliberately split across artifact types and whose valid repair must satisfy behavioral and state invariants. This differs from merely making a patch span more files. Novelty is moderate because ITBench and SpecBench already cover much of the surrounding space.
10. **Possible substrate.** A miniature event-processing system with producer, transformer, consumer, schema registry, configuration overlays, and SQLite state. Fault templates alter serialization, feature-flag precedence, migration ordering, cache invalidation, or idempotency.
11. **Ground truth and verifier.** The generator records the causal edge and valid invariant set. The verifier replays generated histories, checks exact data-state invariants, executes hidden pairwise and three-way compositions, checks forbidden file/test changes, and accepts alternative implementations that preserve the behavior. Diff size is diagnostic, not a hard correctness oracle.
12. **Contamination argument.** Novel topology, schemas, names, event histories, and fault combinations are generated per seed. Public examples can use disjoint namespaces and template combinations.
13. **Long-horizon enforcement.** At least three artifact families must each reveal a necessary fact; replay creates traces that later queries consume; migration or config changes alter subsequent state; an inherited failed replay must be diagnosed and cleaned up; final verification must cover cold start, warm state, retry, and upgrade paths.
14. **Shortcut / reward hack.** Hard-code visible events, bypass schema validation, delete incompatible rows, disable caching/feature flags, replace the pipeline with a monolith, or alter visible tests.
15. **Difficulty by construction.** Component tests exercise artifacts independently and are visible. Hidden checks compose state history with configuration and concurrency. The familiar code-only patch passes visible checks but fails one generated composition.
16. **Build complexity.** Medium-high. The simulator is manageable, but a sound generator that avoids accidental clues and accepts multiple valid repairs is ambitious for one week.
17. **Biggest soundness risk.** Patch minimality is not equivalent to intent preservation. Hard scope limits may reject legitimate alternative designs; soft scope limits may allow broad rewrites that bypass the intended causal reasoning.
18. **Strongest argument against.** This may be SpecBench’s compositional hidden-test idea applied to a small service graph, with no clean way to show the agent actually reconciled artifacts rather than guessed a repair that passed more tests.
19. **Verdict.** **HOLD / fallback.** Prefer only if Candidate 1’s inherited-recovery state machine proves too complex and a verifier spike shows two alternative correct repairs can be accepted.

### Candidate 4 — Durable commitment tracking under emergent specification

**Verdict: REJECT as crowded.**

1. **Capability name.** Maintaining and revising durable implementation commitments as requirements arrive over many turns.
2. **Exact expected model failure.** The agent forgets earlier constraints, implements later requirements in isolation, and leaves structurally inconsistent components.
3. **Primary sources.** SLUMP directly studies this capability; RoadmapBench and SWE-EVO cover multi-target evolution. [[S7]](#s7) [[S8]](#s8) [[S13]](#s13)
4. **What sources prove.** SLUMP reports lower final faithfulness under emergent versus single-shot specification and specifically finds structural-integration degradation. [[S13]](#s13)
5. **What they do not prove.** SLUMP’s 20 research-code targets do not exhaust all forms of evolving product requirements, and its rubric is not a deterministic procedural oracle for every component.
6. **Why users care.** Long-running development rarely starts from a complete specification.
7. **Why labs care.** Specification memory and state tracking are post-training targets; SLUMP’s ProjectGuard result indicates mitigation is possible. [[S13]](#s13)
8. **Closest benchmarks.** SLUMP is directly overlapping; SWE-EVO and RoadmapBench cover large coordinated evolution. [[S7]](#s7) [[S8]](#s8) [[S13]](#s13)
9. **Novelty argument.** Weak. A procedural product-spec variant would change substrate and verifier but not the central capability.
10. **Possible substrate.** Progressive requirements for a small generated API and workflow engine.
11. **Ground truth and verifier.** Constraint ledger plus hidden behavioral tests for every disclosed requirement and interaction.
12. **Contamination argument.** Generated requirements and APIs can be fresh, but the task pattern is now public and explicit.
13. **Long-horizon enforcement.** 30–60 requirement turns, multiple edit/test tools, versioned requirement state, and injected regression feedback can satisfy the mechanics.
14. **Shortcut / reward hack.** Rebuild from the full accumulated transcript at the end, bypassing durable tracking; hard-code tests; or ignore superseded requirements.
15. **Difficulty by construction.** Later requirements compose with earlier ones and visible tests cover them only separately.
16. **Build complexity.** Medium-high because good evolving specifications and independent component oracles take authoring effort.
17. **Biggest soundness risk.** The task measures context retention or transcript reconstruction rather than software-engineering reasoning.
18. **Strongest argument against.** SLUMP was published specifically to identify specification tracking as a distinct long-horizon target; reproducing it would not be an original hiring-trial contribution. [[S13]](#s13)
19. **Verdict.** **REJECT.** Use SLUMP as evidence and a design warning, not as the environment concept.

### Candidate 5 — Release-scale version evolution

**Verdict: REJECT as crowded and infeasible.**

1. **Capability name.** Coordinated implementation of release-level or roadmap-level software evolution.
2. **Exact expected model failure.** The agent implements a subset of targets, misreads release intent, loops, or breaks regression behavior across many files.
3. **Primary sources.** SWE-EVO and RoadmapBench directly measure release/version evolution; SWE-Bench Pro measures larger enterprise issue-resolution tasks. [[S5]](#s5) [[S7]](#s7) [[S8]](#s8)
4. **What sources prove.** SWE-EVO reports 48 multi-step release tasks with broad tests; RoadmapBench reports 115 multi-target upgrades with large median gold changes; both report substantial remaining failure. [[S7]](#s7) [[S8]](#s8)
5. **What they do not prove.** Large diffs do not prove genuine stateful interaction, heterogeneous tools, or forced recovery.
6. **Why users care.** Release work is commercially valuable and closer to team-scale development than one issue.
7. **Why labs care.** These benchmarks avoid saturation and test sustained coordination.
8. **Closest benchmarks.** SWE-EVO and RoadmapBench are direct; SWE-Bench Pro is adjacent. [[S5]](#s5) [[S7]](#s7) [[S8]](#s8)
9. **Novelty argument.** None strong enough. Procedurally generating a release would make the codebase artificial but not create a new measured capability.
10. **Possible substrate.** A generated framework upgraded across several versions.
11. **Ground truth and verifier.** Per-feature tests, regression suite, API compatibility checks, and migration validation.
12. **Contamination argument.** Generation can reduce exposure but sacrifices the realism that motivates release-history benchmarks.
13. **Long-horizon enforcement.** Many dependent targets and tests can create length, but the work may remain a large batch of interchangeable edits rather than a causally stateful workflow.
14. **Shortcut / reward hack.** Copy future-version code if exposed; stub features; disable old behavior; or target visible tests.
15. **Difficulty by construction.** Hidden cross-feature tests and migrations can distinguish partial implementations.
16. **Build complexity.** High to prohibitive for five to seven days if the environment is expected to be deep, original, and convincingly release-scale.
17. **Biggest soundness risk.** The grader inherits the prompt/test mismatch and narrow-reference problems documented in recent SWE-bench audits. [[S3]](#s3) [[S4]](#s4)
18. **Strongest argument against.** Two recent benchmarks already claim this exact territory with substantially larger curation efforts than a one-week prototype can match. [[S7]](#s7) [[S8]](#s8)
19. **Verdict.** **REJECT.** Difficulty would mostly come from scale and step budget, violating the trial’s capability-specificity requirement.

## 4. Benchmark-overlap matrix

Legend: **Direct** = measures substantially the same construct; **Adjacent** = shares substrate or a component capability; **Distinct** = little overlap. The final column states the exact boundary relevant to Candidate 1.

| Benchmark | What it actually measures | Interaction / verifier | Overlap with Candidate 1 | Why Candidate 1 is or is not distinct |
|---|---|---|---|---|
| SWE-bench / Verified | Resolve one real GitHub issue by producing a patch. [[S1]](#s1) | Repository tools plus containerized fail-to-pass/pass-to-pass tests. [[S1]](#s1) [[S2]](#s2) | Adjacent | Candidate 1 starts from a changed, failed-remediation state and requires rollback plus causal discrimination. SWE-bench generally starts from one faulty snapshot. |
| SWE-Bench Pro | Larger, enterprise-oriented repository issues, often multi-file and long-horizon. [[S5]](#s5) | Patch tested against task-specific suites; public/held-out/commercial partitions. | Adjacent | It increases realism and size but does not isolate inherited-fix revision. July 2026 audit makes prompt/test determinacy a caution, not evidence against the construct. [[S4]](#s4) |
| SWE-bench Live | Fresh, continuously curated GitHub issue resolution with per-task containers. [[S6]](#s6) | Patch execution against generated task environments. | Adjacent | Its innovation is freshness/scale; Candidate 1’s is controlled causal state and recovery. |
| SWE-EVO | Release-note-driven multi-step evolution spanning many files and tests. [[S7]](#s7) | Resolved Rate plus partial Fix Rate from fail-to-pass/pass-to-pass suites. | Adjacent | Candidate 1 is deliberately small and stateful; it does not ask for release-wide implementation. |
| RoadmapBench | Multi-target version upgrades across repositories/languages. [[S8]](#s8) | OpenHands-style repository interaction and executable target tests. | Adjacent | Large roadmap completion is not diagnosis revision, rollback, or operational state recovery. |
| Terminal-Bench 2.0 | Broad hard tasks performed in unique terminal environments. [[S9]](#s9) | Human solutions and comprehensive task tests. | Adjacent | Candidate 1 could run in the same broad container paradigm, but targets one causal construct with generated state/oracle. |
| τ-bench | Policy-following user/tool interaction in retail and airline domains. [[S10]](#s10) | Final database state plus pass^k reliability. | Adjacent | It supplies a useful state-verification pattern; it does not involve software artifacts, debugging, patches, or rollback of an inherited fix. |
| OSWorld | Open-ended tasks across real computer applications. [[S11]](#s11) | Executable GUI/CLI environment with task-specific state checks. | Distinct / adjacent on state | Candidate 1 avoids GUI grounding and instead controls a software causal graph. |
| OSWorld 2.0 | Very long professional workflows with dynamic environments, cross-source reasoning, implicit state, and verification challenges. [[S12]](#s12) | Up to 500 steps; binary and partial completion. | Adjacent | It already covers hidden state and recovery phenomena broadly, but not a coding-specific, procedurally grounded causal repair construct. |
| SLUMP | Faithfulness loss when software specifications are progressively disclosed over ~60 requests. [[S13]](#s13) | Component-faithfulness rubric and exposure audit. | Distinct | Specification arrival changes desired behavior; Candidate 1 changes evidence about the cause of already undesired behavior. |
| FixedBench | Decide not to change already-fixed code; also probes partial-fix over-abstention. [[S14]](#s14) | Undesirable non-test/non-doc change rate. | Direct on action calibration, not recovery | Candidate 1 includes an inherited fix but always begins in a failed operational state. The key decision is what to undo and which causal layer to repair, not merely whether to edit. |
| Precise Debugging Benchmark | Resolve generated atomic bugs with edit precision and bug recall. [[S15]](#s15) | Unit tests plus edit-level metrics. | Direct on bounded repair | Candidate 1 accepts broader alternative implementations and adds runtime evidence, deployment state, rollback, and hidden state invariants. |
| debug-gym | Interactive code exploration and debugger-tool use. [[S16]](#s16) | Changing observations from shell/debugger/edit/test tools. | Direct on interaction substrate | It is a reusable environment paradigm, not a benchmark specifically forcing inherited-fix recovery and falsification. |
| ITBench | Realistic SRE, CISO, and FinOps automation scenarios. [[S17]](#s17) | Live IT environments and scenario-specific metrics. | Closest / partially direct | Candidate 1 must prove that its narrower inherited-failure and counterevidence construction yields a cleaner, procedural construct and lighter verifier. Otherwise ITBench subsumes the practical claim. |
| HiL-Bench | Decide when and what to ask as blockers emerge during SWE/SQL work. [[S18]](#s18) | Ask-F1 plus task pass rate and a deterministic answer tool. | Adjacent | Candidate 1’s decisive new evidence comes from machine tools and causal experiments, not necessarily human clarification. |
| SpecBench (reward hacking) | Visible feature-test success versus held-out compositional correctness in long coding tasks. [[S19]](#s19) | Two disjoint test suites and their pass-rate gap. | Adjacent on difficulty construction | Candidate 1 reuses compositional hidden checks but grounds them in incident histories and state invariants rather than greenfield systems implementation. |

### Overlap conclusion

**INFERENCE:** Candidate 1 is not novel merely because it uses logs, traces, a terminal, or a long trajectory; all are occupied. Its defensible novelty is the conjunction of: (1) an inherited repair has already modified the world, (2) that repair has failed and must be recovered from, (3) early evidence supports a decoy diagnosis, (4) later tool-produced counterevidence distinguishes the true cause, and (5) the verifier grades restored state plus counterfactual behavior without requiring the reference diff.

## 5. Ranked comparison

Scores are project judgments from 1 (poor) to 5 (strong). They are not model results. Total is out of 45.

| Rank | Candidate | Evidence | Importance | Novelty | Verifier | Procedural generation | Contamination resistance | Long-horizon | Difficulty by construction | One-week feasibility | Total | Verdict |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Counterevidence-triggered repair revision | 5 | 5 | 4 | 4 | 4 | 5 | 5 | 5 | 4 | **41** | GO |
| 2 | Selective action across maintenance states | 5 | 5 | 3 | 5 | 5 | 4 | 4 | 4 | 4 | **39** | GO fallback |
| 3 | Cross-artifact causal repair | 4 | 5 | 3 | 3 | 4 | 5 | 5 | 4 | 3 | **36** | HOLD fallback |
| 4 | Emergent-specification commitments | 5 | 4 | 1 | 3 | 2 | 3 | 5 | 3 | 2 | **28** | REJECT |
| 5 | Release-scale version evolution | 5 | 5 | 1 | 3 | 2 | 2 | 4 | 3 | 1 | **26** | REJECT |

### Score interpretation

- **Candidate 1 wins** because its causal state machine makes recovery intrinsic and its oracle can be generated. It loses one point on novelty because ITBench/debug-gym are close, one on verifier because belief revision is indirectly observed, one on generation because natural causal decoys are hard, and one on feasibility because verifier QA is substantial.
- **Candidate 2 is easier to verify and generate** but has weaker novelty and a risk of short trajectories, especially for already-fixed cases.
- **Candidate 3 has strong realism and contamination resistance** but the acceptance of alternative repairs and separation of causal reasoning from test search are harder.
- **Candidates 4 and 5 have excellent evidence of difficulty** but fail the originality or feasibility bar.

## 6. Primary recommendation

### Recommend Candidate 1 with a two-day pre-implementation verifier spike

**INFERENCE:** the first proposal should define a single incident family around an inherited failed canary, not a general SRE simulator. A credible example family is an idempotent event-processing service in which a visible duplicate-output symptom can arise from either retry policy or checkpoint ordering. The inherited patch changes retry behavior and causes a second regression. The true repair requires restoring the checkpoint, reproducing under a seeded history, using traces plus state inspection to reject the retry-only theory, changing the ordering boundary, redeploying, and verifying both duplicate suppression and no event loss.

The proposal should commit to these verifier principles:

1. Canonical ground truth is generated before the episode and kept outside the agent runtime.
2. Strict success requires all behavioral, state-integrity, recovery, and tamper-resistance objectives; mean reward can expose partial progress.
3. The reference diff is not the correctness oracle.
4. At least two structurally different correct repairs must pass each validated instance or instance family.
5. Visible feedback must be useful but insufficient: it should admit a familiar symptom-suppression solution that hidden counterfactual workloads reject.
6. The agent’s prose diagnosis is ignored for correctness.
7. The trajectory is used to verify environmental facts—tool calls, revision transitions, rollback occurrence—not hidden mental states.
8. Gold traces must show 15–30+ causally necessary actions, not padding.

### Proposed prototype acceptance gate

Do not proceed from proposal to full implementation unless a hand-built paper instance can demonstrate all of the following:

- untouched state scores below 0.20;
- inherited-patch continuation clears the visible symptom but fails hidden invariants;
- blanket revert alone fails because the original incident returns;
- broad rewrite/stub/feature-disable strategies fail independent objectives;
- two alternative correct repairs score 1.0;
- removing any one required artifact or tool makes the task unsolvable or measurably changes the information available;
- the oracle, generator, and hidden workloads are absent from the agent-visible filesystem and process environment;
- gold execution includes failure detection, rollback or equivalent restoration, corrected repair, and post-recovery verification.

## 7. Two fallback candidates

### Fallback 1 — Selective maintenance action

Choose Candidate 2 if the inherited-failure simulator cannot be made natural or if verifier work exceeds the week. It has the strongest direct evidence and the cleanest final-state labels. Keep it original by evaluating paired latent states with multiple terminal actions, not by recreating FixedBench’s already-fixed split. The acceptance gate is a nontrivial gold horizon and resistance to always-ask, always-abstain, and always-patch policies.

### Fallback 2 — Cross-artifact causal repair

Choose Candidate 3 if a small event-processing substrate is already convincing but forced rollback feels artificial. Retain the generated causal graph and compositional hidden histories; drop the requirement to inherit a bad fix. The acceptance gate is an implementation-agnostic verifier that accepts at least two repairs and a demonstrated visible-test shortcut that fails hidden cross-artifact invariants.

## 8. Strongest objection to the primary recommendation

**The construct may not be separately measurable from ordinary interactive debugging.** A capable agent could ignore the inherited diagnosis, inspect the whole system, and produce a correct final state without ever representing or revising a hypothesis. Conversely, a weak agent could perform the prescribed rollback and evidence-gathering sequence mechanically. Because internal beliefs are unobservable, a final-state verifier may only establish that the agent solved a carefully staged debugging task.

This objection is decisive if the environment cannot show transfer or controlled contrast. The proposal therefore needs paired instances: identical surface symptom and inherited patch, but different latent causes whose discriminating evidence appears only after different experiments. Performance should be compared with ablations that remove the inherited patch, counterevidence, or stateful recovery constraint. If scores barely change, the claimed construct is not load-bearing.

## 9. Evidence that would reverse the decision

The recommendation should change from GO to HOLD or REJECT if any of the following is found during proposal review or the verifier spike:

1. **Direct benchmark overlap:** ITBench, debug-gym, or a newer primary benchmark already contains paired inherited-failed-remediation tasks with deterministic causal ground truth, rollback constraints, and counterfactual state verification.
2. **No construct sensitivity:** removing the misleading inherited diagnosis or failed patch does not materially shorten gold trajectories or improve baseline performance.
3. **Verifier dependence on a reference patch:** alternative correct repairs cannot be accepted without encoding implementation details.
4. **Shortcut dominance:** blanket revert, feature disablement, retry inflation, state deletion, or hard-coded visible IDs can achieve high reward.
5. **Artificial horizon:** the 15–30 action requirement is enforced by locks or arbitrary phase gates rather than information and state dependencies.
6. **Generator leakage:** names, layouts, or fault templates make the true causal layer directly predictable.
7. **One-week infeasibility:** a minimal simulator, oracle, isolation harness, gold solver, alternate solver, and cheat battery cannot be completed and audited within the trial window.
8. **Poor discriminative power:** two current frontier agent configurations both solve nearly all validated instances, or both fail before reaching the intended revision point for unrelated tool/setup reasons.

## 10. Rejected ideas and why

- **Generic “long-horizon coding.”** Rejected because SWE-Bench Pro, SWE-EVO, RoadmapBench, Terminal-Bench 2.0, and OSWorld 2.0 already cover difficult long tasks; size alone does not identify a capability. [[S5]](#s5) [[S7]](#s7) [[S8]](#s8) [[S9]](#s9) [[S12]](#s12)
- **Release-note or roadmap implementation.** Rejected as directly occupied by SWE-EVO and RoadmapBench and infeasible to reproduce deeply in one week. [[S7]](#s7) [[S8]](#s8)
- **Emergent requirements / specification memory.** Rejected as directly occupied by SLUMP, which already uses progressive disclosure and measures faithfulness loss. [[S13]](#s13)
- **Minimal patching by diff size.** Rejected as a standalone concept. Precise Debugging Benchmark already measures edit precision, and raw minimality can penalize legitimate alternative repairs. [[S15]](#s15)
- **Pure abstention on stale issues.** Rejected as directly occupied by FixedBench. The broader selective-action fallback remains viable only because it includes partial state, rollback, escalation, and paired operational evidence. [[S14]](#s14)
- **Pure “ask when uncertain.”** Rejected as directly occupied by HiL-Bench. [[S18]](#s18)
- **Visible-versus-hidden test reward hacking alone.** Rejected as a primary concept because SpecBench directly formalizes that gap. Candidate 1 uses compositional hidden checks as a verifier technique, not as its capability claim. [[S19]](#s19)
- **Full Kubernetes incident response.** Rejected for the one-week prototype because ITBench already provides a mature adjacent framework and the infrastructure burden would dominate capability research. [[S17]](#s17)
- **GUI-based operational recovery.** Rejected because OSWorld 2.0 already covers dynamic long-horizon computer workflows, while GUI grounding would introduce noise unrelated to the proposed software-repair construct. [[S12]](#s12)

## 11. Remaining open questions

1. **OPEN QUESTION — Construct validity:** can paired-instance and ablation experiments demonstrate that inherited-fix recovery and counterevidence are load-bearing rather than narrative decoration?
2. **OPEN QUESTION — Alternative solutions:** what behavioral oracle accepts a rollback-plus-local-fix and a forward-compatible repair while rejecting feature disablement and state deletion?
3. **OPEN QUESTION — Natural causal decoys:** which two or three fault families produce genuinely ambiguous early symptoms without relying on misleading prompts?
4. **OPEN QUESTION — Horizon proof:** what is the shortest gold trajectory under full knowledge, and which steps are causally necessary rather than interface overhead?
5. **OPEN QUESTION — Partial reward:** should evidence collection and rollback be independently rewarded, or only reported as diagnostics to avoid policy shaping toward a single workflow?
6. **OPEN QUESTION — Recovery semantics:** must every valid solution literally roll back, or should any operation that restores the same safe checkpoint be accepted?
7. **OPEN QUESTION — Baseline calibration:** do at least two frontier agent stacks reach the intended counterevidence stage, or do they fail earlier on tool syntax/setup?
8. **OPEN QUESTION — Generator validation:** how many seeds per fault family are needed to estimate false accepts and false rejects with useful confidence intervals?
9. **OPEN QUESTION — Isolation:** can the oracle, generator, hidden histories, and canonical state be kept outside the agent identity while still allowing deterministic local execution?
10. **OPEN QUESTION — Benchmark novelty check:** are there post-July-2026 papers or unretrieved primary artifacts that directly test inherited failed remediation and hypothesis falsification?

## Final decision

**GO to proposal review:** Counterevidence-triggered repair revision under an inherited failed fix.

**Do not implement yet.** First review and approve the narrow capability definition, paired-instance design, final-state oracle, alternative-solution policy, and the proof that recovery and counterevidence are load-bearing. The major uncertainty is whether the proposed environment measures a distinct revision capability or only stages an unusually well-controlled interactive debugging task.
