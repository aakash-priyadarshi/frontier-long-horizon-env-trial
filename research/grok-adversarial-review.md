# Adversarial review: Stateful recovery after failed remediation

**Reviewer role:** Reject-by-default proposal audit  
**Inputs reviewed:** `AGENTS.md`, `research/codex-gap-study.md`  
**Review date:** 12 July 2026  
**Scope:** Proposal review only. No environment implementation.

**Claim labels used below**

- **SOURCE-BACKED FACT:** confirmed against an opened primary paper, official report, or official repository.
- **INFERENCE:** reviewer’s synthesis or design judgment.
- **UNRESOLVED:** evidence still missing for a decisive call.

---

## 1. Executive verdict

### HOLD

Do **not** proceed to environment implementation.

The proposal’s conjunction (inherited failed remediation already applied; misleading early evidence; discriminating experiments; safe-state restoration; counterfactual final-state grading) is not yet shown to be a separately measurable capability. Nearby 2025–2026 primary work—especially **MicroRemed / ThinkRemed**, **R2Act**, **ITBench**, and **PROBE**—already covers remediation after failure, diagnosis-to-action recovery, and operational incident repair more closely than `codex-gap-study.md` acknowledges. The study’s own strongest objection remains unanswered: a final-state verifier cannot observe hypothesis revision, so the named construct may collapse into staged interactive debugging.

A GO recommendation is premature. A REJECT is not yet forced if, and only if, a verifier spike can prove load-bearing ablations, paired causal discrimination, and acceptance of two structurally different correct repairs while rejecting a cheat battery.

---

## 2. The ten strongest objections

1. **Literature gap fatally weakens the novelty claim.** The study does not engage MicroRemed (executable remediation from diagnosis reports with failed-playbook iteration), R2Act (diagnosis-to-action recovery validity), AIOps2025/RCA100 (reasoning-process microservice diagnosis), SWE-Cycle (full-cycle autonomy), or DeepSWE (original long-horizon SE with functional verifiers). **SOURCE-BACKED FACT** that these exist as primary artifacts; **INFERENCE** that Candidate 1’s “no primary source isolates this” statement is incomplete.

2. **ThinkRemed already operationalizes recovery after failed remediation.** MicroRemed’s ThinkRemed loop executes a playbook, verifies, and iterates after failure. That is the practical capability users care about. The proposed environment risks being a format variation with a code/SQLite substrate instead of Ansible/Kubernetes.

3. **Construct is not observable.** “Counterevidence-triggered hypothesis revision” is an internal cognitive claim. Any final-state oracle only measures whether the episode ended correctly after staged evidence. A strong agent can ignore the ticket narrative and solve ordinary debugging; a weak agent can ritualize rollback/inspect steps.

4. **ITBench already occupies the operational substrate.** ITBench provides live Kubernetes-style incidents, heterogeneous observability tools, diagnosis and mitigation scoring, and low SRE success. Without a sharp ablation contrast, Candidate 1 looks like a lighter, synthetic ITBench slice.

5. **Long-horizon mechanics are likely ceremonial.** The proposed 15–30 action lower bound depends on baseline capture, rollback, multi-artifact inspection, redeploy, and multi-workload verification. Several of those steps can be prescribed by the harness rather than forced by information dependence.

6. **Verifier acceptance breadth and cheat resistance are jointly hard.** Accepting two valid repairs while rejecting feature-disable, retry-swallowing, state deletion, and direct DB mutation is a research problem, not a one-week incidental. This is where OpenAI’s SWE-bench audits show evaluators repeatedly fail.

7. **Paired instances are asserted, not demonstrated.** The entire construct-validity rescue depends on paired seeds with identical surface story and different latent causes. No paper instance, discriminating experiment map, or false-clue audit is provided.

8. **Inherited remediation may be narrative decoration.** If the correct gold path is “inspect everything, fix the true fault,” then starting from a bad patch only adds ceremony unless continuing the inherited theory is both locally rewarding and globally fatal.

9. **One-week depth is overclaimed.** The acceptance gate demands simulator, generator, oracle, tools, public/hidden workloads, gold + alternate solvers, familiar wrong solution, cheat battery, leak checks, and receipts. That is a full mini-benchmark, not a focused prototype.

10. **Capability wording overreaches the grader.** The study correctly says belief revision is unobservable, then still markets the capability as belief revision. The honest measurable claim is narrower: stateful repair from an already-botched remediation under deceptive early evidence.

---

## 3. Verified benchmark-overlap table

| Benchmark / primary work | What it actually measures | Inherited failed remediation already applied? | Recovery changes later actions? | Deterministic causal ground truth? | Counterevidence-driven action revision? | Distinct or format variation? |
|---|---|---|---|---|---|---|
| **ITBench** ([arXiv:2502.05352](https://arxiv.org/abs/2502.05352); [repo](https://github.com/itbench-hub/ITBench)) | SRE/CISO/FinOps automation in real IT testbeds; diagnosis + mitigation; final system-state evaluation. Paper reports agents resolve 13.8% SRE / 25.2% CISO / 0% FinOps scenarios. | Not as a required start state. Faults are injected; agents diagnose/mitigate. | Yes for interactive Kubernetes/observability control. | Partial: scenario ground truth for entities, fault chains, plausible mitigations. | Not isolated as a scored construct. | **Closest operational overlap.** Candidate 1 is lighter/synthetic, not clearly a new capability. |
| **debug-gym** ([arXiv:2503.21557](https://arxiv.org/abs/2503.21557); [repo](https://github.com/microsoft/debug-gym)) | Interactive text debugging with pdb/code/shell tools; changing observations. | No. | Yes: tool observations depend on prior actions. | Depends on wrapped repair datasets; not a generated causal oracle for decoys. | Interactive evidence gathering yes; inherited-fix falsification no. | **Interaction substrate, not the claimed construct.** |
| **FixedBench** ([arXiv:2605.07769](https://arxiv.org/abs/2605.07769)) | Abstain vs edit on already-fixed issues; undesirable non-test/doc edits in 35–65% of cases; over-abstention on partial fixes. | “Already fixed” yes; “failed remediation active” no. | Limited: mainly whether to edit. | Human-verified fixed status. | No; action/inaction calibration. | **Adjacent on inherited state, different decision.** |
| **Precise Debugging Benchmark** ([arXiv:2604.17338](https://arxiv.org/abs/2604.17338)) | Generated atomic/multi-bug programs; unit-test pass vs edit precision/bug recall; >76% pass, <45% precision for named frontier models. | No. | Mostly regenerate/edit loops, not operational recovery. | Yes for injected atomic bugs. | No. | **Adjacent on bounded repair only.** |
| **SWE-bench / Verified / Pro / Live** | Issue → patch; container tests. Audits show serious verifier defects on Verified and Pro. | No. | Soft: edits change later tests, but not operational rollback state machines. | Human/PR-derived, often underdetermined. | No. | **Adjacent repository repair.** |
| **SWE-EVO** ([arXiv:2512.18470](https://arxiv.org/abs/2512.18470)) | Release-sized evolution; multi-file Fix Rate. | No. | Sequential evolution, not failed-remediation recovery. | Test-suite based. | No. | **Distinct / crowded on scale, not this construct.** |
| **SWE-Cycle** ([arXiv:2605.13139](https://arxiv.org/abs/2605.13139)) | Env reconstruction, code impl, test generation, FullCycle autonomy on bare repos. | No inherited failed patch. | Cross-phase dependencies yes. | SWE-Judge + tests. | Not causal-diagnosis revision. | **Missed by study; long-horizon autonomy overlap only.** |
| **DeepSWE** ([arXiv:2607.07946](https://arxiv.org/abs/2607.07946); [site](https://deepswe.datacurve.ai/)) | 113 original long-horizon SE tasks; hand-written functional verifiers; contamination-resistant authorship. | No. | Ordinary agentic repo work. | Functional verifiers intended to accept alternatives. | No. | **Missed by study; overlaps on original tasks + alt-solution verifiers, not incident recovery.** |
| **Terminal-Bench 2.0** ([arXiv:2601.11868](https://arxiv.org/abs/2601.11868)) | 89 hard terminal tasks; frontier <65% in paper. | No. | Task-specific. | Per-task tests. | No. | **Broad terminal mastery; format-adjacent only.** |
| **OSWorld 2.0** ([arXiv:2606.29537](https://arxiv.org/abs/2606.29537)) | 108 long professional computer-use workflows; best binary completion 20.6% at 500 steps. | No SE incident construct. | Strong statefulness. | Checkpoint/state checks. | Not debugging-hypothesis revision. | **Adjacent on long horizon/hidden state only.** |
| **SpecBench** ([arXiv:2605.21384](https://arxiv.org/abs/2605.21384)) | Visible feature tests vs held-out compositional tests; reward hacking in long coding. | No. | Implementation trajectory. | Dual test suites. | No. | **Verifier technique overlap, not capability overlap.** |
| **PROBE** ([arXiv:2605.08717](https://arxiv.org/abs/2605.08717)) | Failure-anchored structured recovery guidance after failed SE/agent runs; diagnosis–recovery gap on 257 unresolved cases. | Starts from failed prior attempt (telemetry), but evaluates a recovery framework, not an RL env that forces revision. | Subsequent attempt uses guidance. | Diagnosis labels / recovery outcomes. | Explicitly about post-failure recovery. | **Conceptually close; different deliverable.** |
| **MicroRemed / ThinkRemed** ([arXiv:2511.01166](https://arxiv.org/abs/2511.01166); [repo](https://github.com/LLM4AIOps/MicroRemed)) | Generate executable Ansible playbooks from diagnosis reports; execution-based recovery verification; ThinkRemed iterates after failed remediation. | Diagnosis report provided; failure already present; failed playbooks trigger reflection/retry. Not necessarily an already-applied wrong code patch in-repo. | Yes: probe/execute/verify loop. | Injected fault + recovery status. | Practical revision after failed repair yes; decoy causal discrimination not the scored axis. | **Highest novelty risk. Closest executable recovery loop.** |
| **R2Act** ([arXiv:2607.04623](https://arxiv.org/abs/2607.04623)) | Post-diagnosis recovery-action validity on 302 K8s incidents; high RCA accuracy with low recovery validity (≈36.8–60.3%). | No inherited wrong patch; focuses on choosing valid recovery actions. | Live replay validates actions. | Root-cause labels + admissible action spaces. | Wrong action after correct diagnosis is measured; counterevidence revision across code layers is not. | **High conceptual overlap on recovery validity after diagnosis.** |
| **AIOps2025 / RCA100** ([arXiv:2606.29193](https://arxiv.org/abs/2606.29193)) | Reasoning-process diagnosis over multimodal observability; localization/identification/evidence-grounded reason. | No. | Agent exploration of modalities. | Expert-labeled causal evidence. | Diagnostic reasoning, not stateful code repair after a bad fix. | **Adjacent diagnosis reasoning.** |
| **HiL-Bench** ([arXiv:2604.09408](https://arxiv.org/abs/2604.09408)) | Selective escalation when blockers emerge; Ask-F1; large full-info vs ask gap. | No. | Asking changes available info. | Blocker labels. | Human clarification, not runtime falsification. | **Adjacent judgment, different evidence channel.** |

### Overlap conclusion

**INFERENCE:** Candidate 1 is **not** novel merely for logs, traces, rollback, long trajectories, or hidden tests. Residual novelty, if any, is only the narrow conjunction of:

1. episode begins with an **already applied wrong remediation** that has changed recoverable state;
2. early evidence **rewards the wrong theory**;
3. later discriminating experiments **force a different causal layer**;
4. grader accepts **multiple repairs** via privileged oracle + counterfactual workloads.

That conjunction is still **unproven against MicroRemed/ThinkRemed and R2Act**. Until a paper contrast exists, treat novelty as **contested**, not established.

---

## 4. Construct-validity analysis

### Attack on the central claim

**Can a capable agent ignore the inherited diagnosis and solve ordinary debugging?**  
Yes. Nothing in the proposal prevents a strong agent from discarding the ticket narrative, dumping state/logs/traces, and localizing the true fault. If that path works, “hypothesis revision” was never required—only debugging under incomplete information.

**Can a weak agent mechanically follow rollback and inspection without revising anything meaningful?**  
Yes. If the harness or prompt implies “rollback → inspect logs → inspect traces → patch X,” a policy can satisfy trajectory checks without representing two competing causal theories.

**Is the claimed capability observable?**  
No. Internal belief revision is not observable. Observable proxies are:

- whether the inherited remediation was undone or neutralized;
- whether discriminating evidence tools were used before the final repair;
- whether the final state matches the seeded causal requirement and hidden workloads.

Those proxies measure **procedure and outcome**, not revision.

### Narrowest honest capability the verifier can support

> **Stateful incident repair starting from an already-applied failed remediation, under early evidence that locally supports a decoy cause, graded by restored safe state plus hidden counterfactual workloads and integrity invariants.**

It cannot honestly claim:

> “counterevidence-triggered hypothesis revision”

unless paired ablations show that agents which never encounter the decoy/inherited-failure package succeed at materially higher rates or shorter causal horizons.

---

## 5. Load-bearing ablation plan

| Ablation | If the construct is real, this should… | Result that proves decoration |
|---|---|---|
| Remove inherited failed remediation | Shorten gold trajectory; raise naive baseline success; remove need for safe-state restoration. | Score/horizon nearly unchanged → inherited failure is story. |
| Remove misleading early evidence | Reduce decoy-following failures; accelerate correct localization. | Same decoy-patch rate → decoy evidence unused. |
| Reveal true cause immediately | Collapse to ordinary repair; remove discriminating experiments. | Still long/hard for unrelated reasons → difficulty not from revision. |
| Remove safe-state restoration requirement | Allow forward-only patches on corrupted state; fewer recovery failures. | No change → rollback is ceremonial. |
| Replace heterogeneous tools with one complete diagnostic dump | Eliminate multi-tool necessity; shorten episodes. | No change → tool heterogeneity is UI tax. |
| Remove hidden counterfactual workloads | Allow symptom-suppression / visible-only patches to pass. | Visible+hidden both pass for wrong patches → hidden tests not discriminative. |
| Allow direct editing of canonical state | Enable oracle-bypass cheats; if still blocked by other invariants, state integrity is real. | Direct mutation scores high → verifier incomplete. |

**Decisive decoration proof:** joint ablation of inherited failure + misleading evidence leaves success rate, gold horizon, and cheat-pass rate statistically unchanged versus the full package.

---

## 6. Minimal paired-instance proposal

### Family: idempotent event processor (as in the study)

**Shared visible surface**

- Symptom: duplicate side-effect for request `R`.
- Inherited remediation: patch that tightens/changes retry policy and is already deployed.
- Early evidence: retry-related log lines and a canary that still flakes under the inherited patch.
- Available tools: code/config edit, deploy/rollback, log search, trace query, checkpoint/state inspect, workload runner.

**Pair A — true cause: checkpoint commit ordering**

- Latent fault: checkpoint advances before side-effect commit.
- Discriminating experiment: replay with retries disabled still duplicates; state inspector shows checkpoint ahead of durable effect.
- Valid corrective action: restore safe checkpoint / ordering boundary; keep retries intact; redeploy; preserve no-loss invariant.

**Pair B — true cause: non-idempotent handler under duplicate delivery**

- Latent fault: handler lacks idempotency key for a side-effect channel.
- Same inherited retry patch and similar early retry logs.
- Discriminating experiment: single-attempt delivery still duplicates when upstream redelivers; traces show two handler completions with distinct attempt IDs but same business key.
- Valid corrective action: restore safe state if needed; add idempotency at handler/store boundary; do **not** “fix” checkpoint ordering; redeploy.

Both members should be verifiable by privileged oracle predicates over histories and invariants, not by reference diffs.

---

## 7. Attack against that paired instance

| Attack | How it breaks the pair |
|---|---|
| **Accidental clues** | File names like `checkpoint_order.py` vs `idempotency.py`, or comments left by the generator, collapse discrimination. |
| **Template memorisation** | If Pair A always needs checkpoint and Pair B always needs handler, agents learn seed templates rather than experiments. |
| **Wording leakage** | Ticket text mentioning “ordering” or “exactly-once key” leaks the answer. |
| **Direct file-location clues** | Inherited patch touching only `retry.py` while true fault is elsewhere is fine; if true-fault files are the only recently “TODO” marked files, leakage. |
| **Solution collapse** | A broad rewrite that adds both checkpoint hardening and idempotency passes both members without discrimination. |
| **Reference-diff dependence** | If verifier encodes one patch shape, alternate valid designs (outbox table vs conditional insert) are false rejects. |
| **Shared wrong attractor** | If both members are solved by “disable retries,” the pair fails to force different corrective actions. |

**INFERENCE:** the pair is viable only if the generator forbids joint fixes that satisfy both causal oracles without addressing the seeded fault class, and if early evidence distributions are matched carefully enough that wording/layout cannot classify the member.

---

## 8. Verifier false-accept and false-reject analysis

### Proposed graded axes (from study)

Incident resolution; safe operational state; hidden counterfactual workloads; persisted-state/data integrity; required functionality enabled; regression prevention; canonical configuration; tamper resistance.

### False rejects (valid alternatives)

- Restore equivalent safe checkpoint via replay/rebuild rather than literal `rollback` command.
- Forward-fix that neutralizes the inherited patch in place without a named rollback tool call.
- Alternative idempotency implementations (unique constraint, outbox, conditional write).
- Broader but behaviorally correct refactors that preserve invariants.
- Temporary feature flag during repair if final state re-enables required functionality and hidden workloads pass.

### False accepts (invalid / destructive)

- Disable the failing feature path while visible smoke still “passes.”
- Inflate retries / swallow exceptions so visible flakes disappear.
- Delete conflicting rows / truncate state to make invariants vacuously true.
- Pin service to stale pre-incident version that never serves the failing workload class.
- Hard-code visible request IDs / seed-specific responses.
- Mutate hidden-test configs, workload definitions, or oracle-adjacent files if exposed.
- Patch only the canary controller or monitoring alert thresholds.
- “Success” by stopping the failing worker while leaving corrupted checkpoints.

**INFERENCE:** without explicit negative predicates for each of the above, the verifier will either overfit to one gold patch or accept shortcuts.

---

## 9. Shortcut and reward-hacking battery

Minimum battery before any GO:

1. Untouched baseline.
2. Continue inherited remediation only.
3. Blanket revert only.
4. Visible-smoke symptom suppression (retry/except/disable).
5. Feature-flag off / route disable.
6. Direct SQLite/canonical-state mutation.
7. Hidden-test / workload-config edit.
8. Hard-coded request IDs / seed fingerprints.
9. Stale-version / refuse-redeploy.
10. Data deletion / truncate.
11. Broad rewrite that stubs the pipeline.
12. Trajectory padding (no-op tool spam) if any process reward exists.
13. Oracle/filesystem leakage scan (agent-visible paths).
14. Alternate correct repair A.
15. Alternate correct repair B.
16. Joint over-repair that should fail at least one pair member’s causal predicate.

Any item 2–13 scoring high is a soundness failure. Items 14–15 must score full. Item 16 must not trivially solve the whole family.

---

## 10. Long-horizon causal-step analysis

### Can it honestly enforce all four conditions?

| Condition | Honest enforcement? | Rejection risk |
|---|---|---|
| 15–30+ causally linked actions | **Conditional.** Possible only if discriminating evidence is split and state transitions gate later observations. | Easy to fake with phase locks, mandatory checklists, or no-op tool requirements. |
| Heterogeneous non-interchangeable tools | **Conditional.** Logs ≠ traces ≠ state ≠ deploy. | One mega-dump tool or copy-pasted identical info across tools collapses this. |
| State transitions constrain future actions | **Yes in principle** if rollback restores schema/config and traces exist only after replay. | Fake waits, deploy cooldowns, or “must call tool X twice” are invalid. |
| Failure detection and recovery required | **Yes if every seed starts failed.** | If agents can patch forward without detecting inherited failure and still pass, recovery is optional. |

### Shortest fully informed gold trajectory (paper estimate)

Assume the agent already knows the true cause and valid repair shape:

1. Observe incident / failed canary. *(necessary)*
2. Capture/inspect current revision and whether inherited patch is active. *(necessary)*
3. Restore safe checkpoint/config equivalent. *(necessary if corrupted; else overhead)*
4. Reproduce under controlled history. *(necessary for evidence artifacts)*
5. Query the one discriminating artifact family. *(necessary)*
6. Apply bounded corrective edit. *(necessary)*
7. Redeploy. *(necessary if runtime must load edit)*
8. Run public workload. *(necessary)*
9. Run hidden counterfactual workload / integrity check. *(necessary for grader; may be automatic)*

**Fully informed causal minimum:** roughly **6–10** actions, not 15–30.

**INFERENCE:** the 15–30 claim therefore depends on **information hiding**, not on the repair itself. That is legitimate only if ablations show those extra evidence steps are required for agents that do not receive the answer. It is illegitimate if the harness forces extra ceremonial inspections after the agent already has enough evidence.

Interface overhead likely includes: multiple log-page fetches, redundant status polls, formatting tools, and mandatory “declare diagnosis” steps. Those must not count toward the causal lower bound.

---

## 11. One-week feasibility assessment

### Credible in 5–7 focused days

- One tiny deterministic simulator (single process + SQLite + fake clock).
- One incident family with 2–3 seeds.
- Privileged oracle for those seeds.
- Minimal tool surface.
- Final-state verifier v0.
- One gold solution.
- A few cheat scripts.
- Short README + receipts for the hand-built instances.

### Not credible at claimed depth in one week

- Robust procedural generation of natural decoys.
- 12–20 clean seeds with leak audits.
- Two structurally different valid solvers per seed.
- Full public/hidden workload matrix.
- Tamper-resistant isolation harness.
- Convincing long-horizon proof without ceremony.
- Comparative baseline runs on frontier agents.

### What must be cut to stay credible

1. Drop multi-family ambitions; keep **one** fault family.
2. Hand-author **one pair** (2 seeds) before any generator sophistication.
3. Make trajectory rewards **diagnostic only**, not scored.
4. Defer Kubernetes realism entirely.
5. Treat “15–30 actions” as a **post-spike measurement**, not a build requirement.
6. Replace “belief revision” marketing with the narrow end-state capability wording.

---

## 12. Minimum verifier spike required before implementation

Do not write the environment until a **paper/instance spike** (no full productization) demonstrates all of the following on one hand-built pair:

1. Untouched score ≤ 0.20.
2. Inherited-patch continuation clears visible symptom, fails hidden invariants.
3. Blanket revert alone fails (incident returns) **or** fails a required-functionality/integrity objective.
4. At least five cheat-battery items from §9 fail.
5. Two structurally different correct repairs score 1.0 on the same oracle.
6. Removing inherited failure **or** misleading evidence measurably changes baseline behavior or gold horizon.
7. Oracle/generator/hidden workloads are outside agent-visible filesystem.
8. Documented shortest informed gold path with causal vs overhead labeling.
9. Written contrast note vs MicroRemed/ThinkRemed and R2Act explaining residual novelty in one paragraph with primary citations.
10. Explicit list of accepted equivalent recovery operations (literal rollback not required).

If any of 1–7 fail, remain on HOLD or move to REJECT / fallback candidates.

---

## 13. Exact conditions that should reverse the recommendation

### HOLD → GO

All of:

- Verifier spike §12 passes.
- Ablations show inherited failure + decoy evidence are load-bearing.
- Written novelty contrast vs MicroRemed and R2Act is specific and source-backed.
- Fully informed gold causal length ≥ 15 **or** the long-horizon claim is rewritten downward honestly.
- Cheat battery stays red; alternate repairs stay green.

### HOLD → REJECT

Any of:

- MicroRemed/ThinkRemed or R2Act already contain the same measurable conjunction under different packaging.
- Ablations show no sensitivity to inherited failure/decoy evidence.
- Verifier cannot accept two valid repairs without reference-diff grading.
- Shortcut dominance cannot be closed without phase locks or exact-command matching.
- One-week prototype cannot clear a 2-seed spike with receipts.

### HOLD → fallback Candidate 2 / 3

- If recovery state machine is the failure point, prefer selective maintenance action (Candidate 2).
- If inherited failure is the failure point but causal graph + hidden compositions work, prefer Candidate 3.

---

## 14. Final narrow capability wording the evidence can honestly support

**Supported (provisional, pending spike):**

> Stateful repair of a small deterministic service incident that begins after an already-applied remediation has failed, where early runtime evidence locally supports a decoy cause, and success is defined by safe-state restoration (or equivalent), correct causal-layer repair, preserved invariants, and hidden counterfactual workloads—without requiring a reference diff or a prose diagnosis.

**Not supported by current evidence:**

> Counterevidence-triggered internal hypothesis revision as a distinctly measured cognitive capability of frontier coding agents.

---

## Research integrity audit of `codex-gap-study.md`

Checked against opened primary sources. Labels apply to the study’s load-bearing claims.

| Claim in study | Label | Notes |
|---|---|---|
| FixedBench: undesirable changes in 35–65% of already-fixed cases | **VERIFIED** | Abstract of [arXiv:2605.07769](https://arxiv.org/abs/2605.07769). |
| Precise Debugging: >76% test pass, <45% precision | **VERIFIED** | Abstract of [arXiv:2604.17338](https://arxiv.org/abs/2604.17338). |
| ITBench: 13.8% SRE resolution among 94 scenarios | **PARTIALLY SUPPORTED** | Abstract states 13.8% SRE / 25.2% CISO / 0% FinOps; Table 4 shows GPT-4o diagnosis pass@1 ≈13.81% and mitigation ≈11.43%. “Resolve” is slightly ambiguous. |
| OpenAI July 2026 Pro audit: ~30% broken; pipeline 27.4%; human 34.1%; recommendation retracted | **VERIFIED** | [OpenAI post](https://openai.com/index/separating-signal-from-noise-coding-evaluations/). |
| OpenAI Feb 2026 Verified audit: 59.4% of 138 audited tasks material issues | **VERIFIED** | [OpenAI post](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/). Study correctly notes failure-enriched subset. |
| Terminal-Bench 2.0: 89 tasks; frontier <65% | **VERIFIED** | Abstract of [arXiv:2601.11868](https://arxiv.org/abs/2601.11868). |
| OSWorld 2.0: 108 workflows; 20.6% best binary at 500 steps | **VERIFIED** | [arXiv:2606.29537](https://arxiv.org/abs/2606.29537). |
| HiL-Bench: large full-info vs ask gap; best tool-enabled SWE pass@3 12% vs 64–88% full info | **VERIFIED** for gap magnitudes in paper text/PDF excerpts; **PARTIALLY SUPPORTED** for “300 tasks” (count not confirmed in opened abstract excerpts). |
| SpecBench: visible vs held-out compositional divergence | **VERIFIED** | Abstract/setup of [arXiv:2605.21384](https://arxiv.org/abs/2605.21384). |
| PROBE: diagnosis–recovery gap; 257 unresolved cases; recovery framework not RL env | **VERIFIED** | Abstract of [arXiv:2605.08717](https://arxiv.org/abs/2605.08717). |
| “No current primary source isolates counterevidence-triggered revision after inherited failed repair” | **OVERSTATED** | True that no source uses that exact phrase; **false as a practical novelty claim** once MicroRemed/ThinkRemed and R2Act are included. Study search scope omitted these. |
| Candidate 1 novelty vs ITBench/debug-gym only | **OVERSTATED** | Misses closer remediation/recovery work. |
| debug-gym establishes interactive runtime inspection as distinct setting | **VERIFIED** | Paper abstract. |
| One-week deep prototype with full acceptance gate is credible | **OVERSTATED** | Feasible only if scope cut hard; full gate is not one week. |
| Belief revision can be graded indirectly via final state + limited trajectory checks | **PARTIALLY SUPPORTED** | Final state is gradable; “revision” remains an interpretation. Study itself flags this. |
| SWE-Cycle / DeepSWE / MicroRemed / R2Act considered | **NOT VERIFIED** | Absent from study tables despite relevance. |

### Separation

- **Source-backed facts:** numerical claims above marked VERIFIED; existence and high-level constructs of MicroRemed, R2Act, SWE-Cycle, DeepSWE, AIOps2025/RCA100.
- **Inference:** Candidate 1 should be HOLD; novelty residual is narrow and unproven; 15–30 actions are information-hiding dependent; one-week full gate is unrealistic.
- **Unresolved:** whether a 2-seed spike can make inherited failure + decoy evidence load-bearing; whether an implementation-agnostic oracle can accept two repairs while blocking joint over-repair; whether frontier agents reach the revision stage or fail earlier on tools.

---

## Primary sources checked for this review

Opened/used as primary evidence (papers, official posts, or official repos/pages):

1. ITBench — arXiv:2502.05352  
2. debug-gym — arXiv:2503.21557 (+ repo page)  
3. FixedBench — arXiv:2605.07769  
4. Precise Debugging Benchmark — arXiv:2604.17338  
5. OpenAI SWE-bench Verified audit post  
6. OpenAI SWE-Bench Pro audit post  
7. Terminal-Bench 2.0 — arXiv:2601.11868  
8. OSWorld 2.0 — arXiv:2606.29537  
9. HiL-Bench — arXiv:2604.09408 (HTML + PDF excerpts)  
10. SpecBench — arXiv:2605.21384  
11. PROBE — arXiv:2605.08717  
12. MicroRemed — arXiv:2511.01166 (+ GitHub)  
13. R2Act — arXiv:2607.04623  
14. AIOps2025/RCA100 multi-dataset diagnosis benchmark — arXiv:2606.29193  
15. SWE-Cycle — arXiv:2605.13139  
16. DeepSWE benchmark — arXiv:2607.07946 (+ project page)  
17. E2E-REME / MicroRemed context — arXiv:2604.11094  
18. Study-cited SWE-bench family context via OpenAI posts and DeepSWE’s related-work discussion  

(Additional study citations such as SWE-EVO/RoadmapBench/SLUMP were treated as already tabulated in the study; this review did not re-open every secondary SWE-family PDF when the overlap conclusion did not depend on new numerical claims.)
