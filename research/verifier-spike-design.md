# Verifier spike design: paired recovery incidents in a deterministic event service

**Status entering this spike:** HOLD  
**Scope:** proposal and verifier design only; no environment implementation  
**Paired-instance result:** the event-processing family survives detailed design  
**Decision:** Candidate 1 should be retained under the narrower observable claim and advanced only to a verifier implementation spike.

## Technical summary

- **The pair is viable.** Both members use the same source tree, ticket, inherited retry mitigation, visible symptom, normalized early logs, public workloads, and tool interface. Instance A activates a worker/effect commit-boundary fault; Instance B activates an ingress/idempotency commit-boundary fault. Their discriminating experiments and correct repair layers differ.
- **The inherited remediation is load-bearing.** Revision `r1` reduces the delivery-attempt budget from three to one. It was already deployed and leaves persisted incident state behind. Even a correct causal repair fails the verifier if `r1` remains active, because a hidden transient-sink workload then loses an accepted occurrence.
- **The familiar wrong solution is credible and discriminative.** Restoring the retry budget while adding a non-atomic worker-side `processed_event` marker clears all three public workloads on both members. Hidden A crashes after the effect but before the marker and duplicates one event; hidden B retries an ingress request after a response timeout and creates two event IDs for one command. The same visible success is therefore exposed by different hidden evidence.
- **The verifier is implementation-independent in principle.** It grades accepted occurrences against net durable effects, cursor/journal consistency, required behavior, canonical configuration, deployment health, deterministic resource bounds, and tamper evidence. It never compares the submitted patch with a reference diff or scores a prose diagnosis.
- **Two structurally different repairs can score 1.0 on Instance A.** One uses an atomic intent/outbox boundary; the other makes the effect ledger idempotent with a stable effect key. Both satisfy the same end-state predicates.
- **The honest action count clears the gate.** A cause-aware shortest path is 14 actions. A pair-blind realistic path is 22 actions when the first discriminating experiment is positive and 26 when the first experiment is negative and the second is required: 24 expected over the matched pair. The 22-action path contains 18 causal or information-gathering actions and four verification actions; it contains no polling, waiting, declarations, paging, or syntax retries.
- **Novelty remains narrow and contested.** MicroRemed/ThinkRemed already evaluates executable remediation and iterative reflection; R2Act already evaluates recovery-action validity after diagnosis; ITBench already covers interactive operational repair. The remaining distinction is only the required conjunction of an already-applied unsafe remediation, matched deceptive evidence, paired code-level causal faults, recovery of persisted state, alternative valid repairs, and counterfactual behavioral grading.

### Claim labels

- **SOURCE-BACKED FACT:** supported by a linked primary paper or official repository already cited in the two prior reports and rechecked for this spike.
- **DESIGN CLAIM:** a property this hand-authored specification intends to enforce; it is not an empirical result until implemented and tested.
- **PREDICTION:** an expected effect of an ablation or shortcut; it must be verified during the implementation spike.
- **UNVERIFIED ADDITIONAL CLAIM:** none is used. Numerical benchmark claims are avoided except where directly stated in the linked primary source.

## 1. The measurable claim is stateful repair, not internal belief revision

### Observable capability

> **Stateful repair of a small deterministic service incident that begins after an already-applied remediation has failed, where matched early runtime evidence locally supports a decoy cause, and success requires safe-state restoration or equivalent forward recovery, repair of the active causal layer, preserved delivery and data invariants, and hidden counterfactual workload success.**

The environment measures whether the agent can produce the following observable sequence and outcome:

1. establish which revision and persisted state are active;
2. stop further unsafe state accumulation;
3. neutralize the inherited remediation and restore or equivalently reconcile persisted state;
4. use non-interchangeable runtime evidence to distinguish the active fault boundary;
5. modify code/configuration at a behaviorally valid layer;
6. deploy the candidate;
7. preserve accepted work, exactly-once net effects, retry support, repeat-occurrence support, canonical configuration, and state consistency under public and hidden workloads.

### What it does not measure

- It does **not** measure an internal hypothesis, belief, reflection, or revision process.
- It does **not** require the agent to state a diagnosis.
- It does **not** require a literal rollback command if an equivalent forward recovery satisfies every final-state predicate.
- It does **not** grade similarity to a reference patch, edit distance, file count, or prescribed tool order.
- It does **not** claim realistic cloud operations, Kubernetes competence, GUI use, or general SRE skill.
- It does **not** establish model weakness until agent baselines are run after the verifier spike.

## 2. Novelty survives only as a narrow matched-pair evaluation design

The comparison below intentionally understates rather than overstates the residual contribution.

| Comparator | Source-backed scope | Overlap | Remaining distinction in this design | Novelty judgment |
|---|---|---|---|---|
| MicroRemed / ThinkRemed | **SOURCE-BACKED FACT:** [MicroRemed](https://arxiv.org/abs/2511.01166) evaluates end-to-end microservice remediation by generating executable Ansible playbooks from diagnosis reports; ThinkRemed adds iterative reasoning and system reflection after execution feedback. | Executable remediation, verification, and retry after a failed playbook are directly overlapping. | The proposed episode starts after one specific remediation has already changed editable code/configuration and persisted service state. Causal diagnosis is not supplied; a matched pair requires different experiments and code-level repair layers; multiple repairs are accepted by hidden behavioral predicates. | **Highest novelty risk.** New remediation as a category is not claimed. |
| R2Act | **SOURCE-BACKED FACT:** [R2Act](https://arxiv.org/abs/2607.04623) evaluates diagnosis-to-action recovery using incident-specific action spaces, valid/invalid plans, offline evaluation, and live replay over 302 quality-audited incidents. | It directly measures whether a correct diagnosis becomes a valid recovery action. | R2Act begins from synchronized observations and root-cause labels/annotated action spaces. This pair withholds the causal layer, requires active discriminating experiments, permits code/config edits rather than plan selection, and grades repaired persisted state plus hidden workloads. | **Strong conceptual overlap; residual distinction is pre-action discrimination plus code repair.** |
| ITBench | **SOURCE-BACKED FACT:** [ITBench](https://arxiv.org/abs/2502.05352) provides 94 scenarios across SRE, CISO, and FinOps in extensible IT testbeds. | Interactive operational diagnosis and mitigation are already occupied. | This design sacrifices infrastructure realism to isolate a two-member causal contrast with identical surface artifacts, a mandatory inherited bad remediation, a deterministic oracle, two valid implementations, and explicit false-accept controls. | **Different measurement instrument, not a broader practical capability.** |
| debug-gym | **SOURCE-BACKED FACT:** [debug-gym](https://arxiv.org/abs/2503.21557) is an interactive text debugging environment with code and debugger tools whose observations change after actions. | Interactive evidence gathering and patch/test loops overlap. | debug-gym is a general environment over repair datasets. It does not make an already-applied unsafe remediation, persisted recovery, paired deceptive evidence, and counterfactual incident-state grading the task definition. | **Interaction substrate overlap; construct remains narrower.** |
| FixedBench | **SOURCE-BACKED FACT:** [FixedBench](https://arxiv.org/abs/2605.07769) evaluates whether agents abstain from modifying already-fixed code and reports action bias plus over-abstention on partial fixes. | Both begin from code already changed by someone else and test action calibration. | Here the current state is known to be unsafe and requires action; abstention cannot pass. The decision is which state to recover and which causal layer to repair. | **Adjacent inherited-state decision, different terminal action.** |
| Precise Debugging Benchmark | **SOURCE-BACKED FACT:** [PDB](https://arxiv.org/abs/2604.17338) generates verified atomic bugs and evaluates test success, edit precision, and bug recall. | Targeted repair and over-editing concerns overlap. | This pair grades a live persisted world, deployment/config state, recovery provenance, and operational counterfactuals. Diff minimality is diagnostic only; two structurally different implementations can pass. | **Bounded-repair overlap, different oracle and state model.** |
| PROBE | **SOURCE-BACKED FACT:** [PROBE](https://arxiv.org/abs/2605.08717) structures failed-run telemetry into evidence, diagnosis, and bounded recovery guidance and reports a diagnosis–recovery gap. | It is explicitly failure-anchored and recovery-oriented. | PROBE evaluates a recovery-guidance framework across subsequent attempts. This design is an executable paired environment whose reward ignores prose guidance and depends on final canonical state, alternative implementations, and hidden workloads. | **Close motivation, different evaluand.** |

### Defensible novelty statement

**DESIGN CLAIM:** The remaining contribution is not “agents must recover failures.” It is a controlled evaluation instrument in which two nearly indistinguishable episodes begin after the *same* bad remediation has changed both code/configuration and persisted state, yet only different active experiments expose different causal boundaries and different repair layers. The design is scientifically useful only if the ablations in Section 13 prove that the inherited remediation, matched early evidence, recovery semantics, tool separation, and hidden workloads each change the shortest valid path or shortcut outcomes.

## 3. The shared substrate is one process, one database, and a fake clock

### Shared ticket and visible presentation

Both members use the exact ticket text below; aliases are generated independently but have the same format.

> After yesterday's mitigation reduced delivery retries, request alias `Q-41` still produced two settlement records. The public canary is green once, but the incident remains open because the mitigation also dropped a recovery attempt. Restore safe operation and resolve the duplicate without disabling settlement delivery or retry support.

The initially visible log excerpt is normalized and identical in both members:

```text
t=041 intake accepted alias=Q-41
t=042 delivery window opened alias=Q-41 attempt=1
t=043 delivery boundary interrupted alias=Q-41
t=044 delivery window opened alias=Q-41 attempt=1
t=045 settlement observed alias=Q-41 count=2
```

The excerpt deliberately omits internal event IDs, command IDs, journal positions, and stage names. Those become available only through later evidence tools.

### Components

| Component | Minimal responsibility | Editable? | Why retained |
|---|---|---:|---|
| Intake | Accepts a command, assigns or reuses an event identity, and appends one journal record. | Yes | Instance B's active fault boundary. |
| Relay | Reads the next journal position, requests a settlement effect, and advances a cursor. | Yes | Instance A's active fault boundary. |
| Effect ledger | Stores settlement effects and compensating effects; exposes net-effect queries. | Yes through code/API, not direct DB writes | Needed for exactly-once net behavior and alternative A2. |
| State store | One SQLite database containing the journal, cursor, effects, optional intents, idempotency rows, recovery metadata, deployment metadata, and audit chain. | Schema/source editable; canonical rows not agent-editable | Gives deterministic persisted state without cloud infrastructure. |
| Fake scheduler | Advances integer ticks, executes named generic cutpoints, injects one crash/timeout/transient failure, and restarts components deterministically. | Harness-visible configuration only | Makes ordering and replay reproducible. |
| Telemetry recorder | Appends normalized logs and span records outside restored service state. | No | Recovery must not erase forensic evidence. |
| Release controller | Activates `r0`, inherited `r1`, or an agent candidate revision. | Through tool only | Makes deployment state explicit and auditable. |

### Neutral source layout and leak controls

Both members ship byte-identical editable source, public tests, filenames, comments, recent diffs, and package layout:

```text
service/
  contract.md
  flow.py
  store.py
  runtime.py
  settings.toml
```

- No file is named for “checkpoint,” “idempotency,” “retry bug,” or either instance.
- `flow.py` contains both intake and relay stages using neutral stage labels `s1` through `s6`.
- No TODO, blame annotation, recent change, exception message, or comment names the active fault.
- `r0 → r1` is identical in both members and changes only the shared attempt policy described below.
- The member selector is a privileged adapter capability in the verifier runtime. It is absent from agent-visible configuration, environment variables, paths, process arguments, logs, and trace attributes.
- Public aliases, internal IDs, table row order, and telemetry correlation handles are regenerated between runs, preventing hard-coded identifiers.

### Persisted state

The canonical schema holds:

- `journal(seq, event_id, command_key, occurrence_id, payload_hash, accepted_tick)`
- `cursor(stream, committed_seq)`
- `effects(effect_id, occurrence_id, amount, kind, source_event_id, committed_tick)`
- `intents(intent_id, source_event_id, occurrence_id, state)`
- `event_marks(event_id, mark_state)`
- `command_keys(command_key, occurrence_id, event_id, state)`
- `recovery_snapshots(snapshot_id, signed_root, cursor_seq, journal_root, effect_root)`
- `deployments(revision, code_root, config_root, activated_tick, status)`
- `audit_chain(seq, action_kind, prior_root, resulting_root, actor)`

### Fake time and ordering

- Time is an integer tick. Each component transition consumes exactly one tick.
- A workload declares input commands and at most one generic cutpoint such as `s2.exit` or `s5.exit`.
- The fake scheduler can interrupt exactly after a named stage commits and before the next stage begins.
- Restarts preserve SQLite and telemetry, but reset in-memory attempt counters.
- There is no sleep, wall-clock race, network timing, or probabilistic retry.

### Deployment revisions

| Revision | Meaning | Attempt budget | Transient sink behavior | Initial status |
|---|---|---:|---|---|
| `r0` | Base service containing both possible dormant boundary weaknesses. | 3 | Retry | Available, not active |
| `r1` | Inherited remediation based on the decoy “too many relay retries.” | 1 | Stop after first failed attempt | Active and unsafe |
| `r2+` | Agent candidate derived from any visible revision. | Must resolve to canonical budget 3 | Must retain retry | Not deployed initially |

### Recovery semantics

The episode starts with signed snapshot `S0`, created immediately before alias `Q-41`. The agent can recover in either of two implementation-independent ways:

1. **Restore path:** pause intake, activate safe code/config, restore `S0`, then replay accepted work with the candidate repair.
2. **Forward-recovery path:** pause intake, activate a candidate containing canonical retry behavior, append compensating records for excess net effects, reconcile cursor/intents from the journal, and preserve all accepted occurrences.

Literal deletion of canonical rows is never a recovery operation. A valid recovery must leave a signed audit transition and must preserve the set of accepted occurrences.

### Public and hidden workloads

| Workload | Visibility | Shared or member-specific | Behavior checked |
|---|---|---|---|
| `P1 routine-redelivery` | Public | Shared | Requeues the same event ID after a failure *before* any effect commit; expects one net effect. |
| `P2 transient-effect-failure` | Public | Shared | Fails the ledger before effect commit once; expects retry and eventual one net effect. |
| `P3 unique-occurrences` | Public | Shared | Processes three commands with distinct keys/occurrences; expects three effects within the public tick budget. |
| `H-A1 cutpoint-replay` | Hidden | A | Interrupts after effect commit but before relay completion; expects one net effect after restart. |
| `H-A2 repeatable-key` | Hidden | A | Sends two legitimate occurrences sharing a business key; expects both effects and rejects coarse cross-occurrence dedupe. |
| `H-B1 response-timeout-retry` | Hidden | B | Times out after journal append and retries the same command/occurrence; expects one journal identity and one net effect. |
| `H-B2 provenance-check` | Hidden | B | Confirms no two accepted journal events derive from one idempotent command occurrence. |
| `H-S1 recovery-regression` | Hidden | Shared | Replays all pre-incident accepted work and verifies no loss, no excess net effect, retry enabled, intake resumed. |
| `H-S2 compatibility-budget` | Hidden | Shared | Checks repeat-occurrence semantics and a declared maximum of four durable state mutations per newly accepted occurrence. |

### What the inherited remediation changed and why the world is unsafe

`r1` changes `attempt_budget = 3` to `attempt_budget = 1`. It does not repair either active causal fault. It is unsafe for both members because `P2`-style transient effect failure can lose an already accepted occurrence. The initial world also contains two settlement effects attributed to alias `Q-41`; recovery must remove the excess *net* effect by signed snapshot restoration or a compensating record. Merely shipping correct future code without repairing this persisted state fails.

## 4. Paired Instance A: effect commit and relay progress are not one recoverable operation

| Required field | Concrete design |
|---|---|
| Latent fault | The active adapter commits an effect at stage `s5`, then allows a deterministic interruption before relay progress at `s6`. Restart replays the same event, causing a second effect. |
| Decoy causal explanation | “The relay retried too many times.” The initial logs show two attempt windows, and `r1` was explicitly deployed to reduce attempts. |
| Inherited failed remediation | Shared `r1`: attempt budget reduced from 3 to 1. It fails because restart replay is driven by unadvanced persisted progress, not the in-memory retry loop. |
| Initial world state | `r1` active; intake open; snapshot `S0` available; one accepted occurrence after `S0`; one journal event for it; cursor eventually at that sequence; two effects for the same occurrence after restart; no valid intent tying progress and effect together; telemetry preserved. |
| Visible symptom | Alias `Q-41` has two settlement effects. Public canary summary is identical to B. |
| Early evidence | Matched normalized log excerpt; active revision shows `r1`; public effect count is 2. Early evidence does not expose whether there was one event replayed or two events accepted. |
| Discriminating experiment | From restored `S0`, run one command while interrupting `s5.exit` once, then restart and allow completion. This is the relay-boundary experiment. |
| Evidence produced | Logs provide a new correlation handle. Trace shows one intake span, one journal identity, two relay epochs, and an interruption between `s5` and `s6`. State inspection using the trace selector shows one journal row, one occurrence, two effect commits, and progress absent after the first effect. |
| Safe-state recovery options | Restore: pause, rollback/neutralize `r1`, restore `S0`. Forward: pause, canonicalize retry policy, append a compensating effect for the excess record, reconcile progress to the journal, retain audit provenance. |
| Valid corrective actions | Atomic intent/progress transition with idempotent dispatch; or stable effect identity enforced by the ledger so replay cannot add a second net effect. |
| Invalid symptom suppression | Worker marker written after effect; attempt budget 0/1; swallow interruption; disable restart/retry; delete duplicate row; dedupe by broad business key; pin to stale code. |
| Public checks | P1, P2, P3 all pass after a valid repair. |
| Hidden checks | H-A1 exposes the effect/marker crash window; H-A2 ensures repeated legitimate occurrences are preserved; H-S1 and H-S2 enforce recovery, retry, and compatibility. |
| Canonical final invariants | One net effect per accepted occurrence; no event loss; cursor at maximum contiguous settled journal sequence; no orphaned intent/mark; attempt budget 3; intake open; candidate healthy; signed recovery provenance; mutation budget satisfied. |

### Why A does not reduce to “add a dedupe table”

A marker written after the effect leaves the same interruption window. A marker written before the effect prevents duplication but loses the effect if interruption occurs after the marker and before the effect. The verifier accepts a marker-based solution only if its state transition is made atomic with the effect intent or if the effect sink independently enforces a stable identity.

## 5. Paired Instance B: command acceptance and idempotency registration are not one recoverable operation

| Required field | Concrete design |
|---|---|
| Latent fault | The active adapter appends a journal event at stage `s2`, then permits a response timeout before the command-key row becomes durable at `s3`. Retrying the same command occurrence appends a second event ID; the relay correctly processes each once. |
| Decoy causal explanation | The same “relay retried too many times” story. Normalized early logs expose two delivery windows but not that they came from two event IDs. |
| Inherited failed remediation | The same shared `r1`. It cannot prevent two first-attempt deliveries of two distinct event IDs and also creates the shared transient-loss regression. |
| Initial world state | `r1` active; intake open; `S0` available; two journal rows with different event IDs but the same command/occurrence lineage; cursor covers both; one effect per event ID, therefore two net effects for one accepted command occurrence; command-key row points only to the second event. |
| Visible symptom | Alias `Q-41` has two settlement effects, with the same ticket and normalized early logs as A. |
| Early evidence | Active `r1`, two effect observations, and two normalized attempt windows. Direct IDs and journal provenance remain unavailable until correlated trace/state queries. |
| Discriminating experiment | From restored `S0`, submit one command, interrupt `s2.exit` so the response is not observed, then retry the same command and occurrence. This is the intake-boundary experiment. |
| Evidence produced | Trace shows two intake spans with one command lineage, two distinct event identities, and one relay completion for each. State inspection shows two journal rows, cursor consistent, no worker replay, and the command-key row committed only for the second event. |
| Safe-state recovery options | Restore `S0` after neutralizing `r1`; or forward-reconcile by compensating the excess effect and collapsing the duplicate journal lineage without deleting an accepted occurrence record from the audit history. |
| Valid corrective actions | Make event append and command-key registration one atomic transaction; or derive/reuse a stable event ID from `(command_key, occurrence_id)` so retry cannot create a new journal identity. |
| Invalid symptom suppression | Worker event-ID marker; reduce attempts; swallow intake timeout; delete one event/effect without compensation/provenance; coarse dedupe across different occurrences; disable retries. |
| Public checks | The same P1, P2, and P3 all pass after a valid repair. |
| Hidden checks | H-B1 and H-B2 expose two event IDs from one idempotent command; H-S1 checks recovery and retry; H-S2 checks occurrence compatibility and mutation budget. |
| Canonical final invariants | One accepted journal identity and one net effect per idempotent command occurrence; distinct occurrences remain distinct; cursor contiguous; command-key mapping total and unambiguous; attempt budget 3; intake open; candidate healthy; audit and mutation bounds satisfied. |

### Why the pair requires different repairs

- A's intake lineage is already correct; its active failure is after journal acceptance, at effect/progress recovery.
- B's relay behavior is already correct; its active failure is before relay processing, at command/event acceptance.
- A's discriminating experiment interrupts `s5.exit`; B's interrupts `s2.exit` and retries the command.
- An unconditional “business-key dedupe everywhere” loses legitimate repeated occurrences in H-A2/H-S2.
- An unconditional implementation of both full repair stacks adds two independent durable coordination writes and exceeds H-S2's declared mutation budget. A genuinely optimized, contract-aware generalized implementation may still pass; it is accepted as a valid general solution because the verifier grades behavior and resource contract, not patch breadth. Such a solution is not a shortcut: it must implement both semantics correctly and remain within the same bound.

## 6. Explicit world-state model

### State variables and initial values

| State variable | Agent-visible representation | Initial A | Initial B | Canonical final requirement |
|---|---|---|---|---|
| Fake clock | Current integer tick via status/workload receipts | 45 | 45 | Monotonic; no unexplained gaps; final value depends on valid path. |
| Intake state | `open` / `paused` via release status | Open | Open | Open only after recovery and candidate verification. |
| Active revision | Revision label and roots via release status | `r1` | `r1` | Healthy candidate root; not `r0` or `r1`. |
| Inherited remediation status | Derived from active config root, not a prose flag | Active | Active | Neutralized; attempt budget exactly 3 and transient behavior retry. |
| Candidate workspace root | Hash of proposed source/config | None | None | May vary; must match deployed healthy root. |
| Cursor | Stream and committed sequence via selector-based state inspection | Covers incident sequence after replay | Covers both incident events | Maximum contiguous sequence whose required net effects are settled. |
| Journal | Selector-limited rows | One event for incident occurrence | Two events for same command occurrence | A: one incident event retained. B: one effective accepted identity per idempotent occurrence; audit history may record collapsed duplicate provenance. |
| Effect records | Net and provenance query, not raw dump | Two positive effects for one occurrence | Two positive effects for one occurrence | Exactly one positive net effect per accepted occurrence. Compensation is allowed and must be linked. |
| Intents | Selector-limited state | None for incident | Not required by base | No orphaned or doubly dispatched intent; optional depending on valid implementation. |
| Event marks | Selector-limited state | None initially | None initially | Optional; if used, no mark/effect/progress inconsistency under cutpoints. |
| Command-key mapping | Selector-limited state | One correct mapping | Mapping to only second event | Total and unambiguous for idempotent occurrences. |
| Canary status | Pass/fail and public workload receipts | Misleading single pass after r1 | Same | All public workloads pass on candidate. |
| Workload history | Public receipt list; hidden runs privileged | Incident plus inherited canary | Matched count/shape | All public and hidden receipts attributable to immutable workload roots. |
| Generated logs | Filtered normalized records | Matched excerpt | Matched excerpt | Append-only; no requirement on exact text beyond integrity root. |
| Generated traces | Correlation-scoped spans | One event replay hidden until query | Two-event lineage hidden until query | Spans consistent with journal/effects and no missing required stage completion. |
| Data-integrity status | Derived summary with predicate failures | Failed: excess net effect | Failed: excess net effect + ambiguous command lineage | All integrity predicates true. |
| Signed recovery snapshot | ID/root revealed only after state inspection | `S0`, available | `S0`, available | Restore used, or forward recovery proves equivalent accepted-occurrence and net-effect roots. |
| Recovery provenance | Audit-chain entries | None after inherited deployment | None | Signed restore or compensating reconciliation recorded. |
| Durable mutation count | Per-workload count in receipts | Not yet evaluated | Not yet evaluated | At most four durable mutations per newly accepted occurrence under H-S2. |
| Fixture/workload roots | Hashes visible; contents public only for P workloads | Canonical | Canonical | Unchanged; hidden roots inaccessible to agent. |
| Final incident status | Derived, never agent-set | Open | Open | Closed only when every strict predicate passes. |
| Member selector | No agent-visible representation | Privileged A adapter | Privileged B adapter | Never exposed; used only to configure hidden cutpoint behavior/oracle. |

### Tool actions and state effects

| Action | Reads | Changes | Preconditions | Important downstream dependency |
|---|---|---|---|---|
| `release.status` | Tick, intake, active revision/config roots, public canary receipts, incident summary | None | None | Establishes which code/config and unsafe intake state subsequent recovery actions target. |
| `workspace.read(path)` | One public source/config/contract file | None | Valid public path | Stage semantics and repair location; no runtime evidence. |
| `workspace.edit(patch)` | Candidate workspace root and targeted public files | Candidate workspace/root only | Patch applies to public files | `release.deploy` activates exactly this root. |
| `telemetry.logs(alias, window)` | Normalized log records matching alias/time | None | Workload/incident has produced logs | Returns correlation handle required by trace query. |
| `telemetry.trace(handle)` | Span lineage for one handle | None | Handle came from log query | Returns internal event/command selectors required by state inspection. |
| `state.inspect(selector, view)` | Selected journal/cursor/effect/intent/key rows; signed snapshot availability | None | Selector from trace or named public stream | Establishes durable provenance; provides valid recovery snapshot ID. |
| `recovery.pause` | Intake state | Sets intake paused; appends audit event | Intake open | Prevents new journal/effect mutations during rollback/restore/reconcile. |
| `recovery.restore(snapshot_id)` | Signed snapshot and current roots | Restores canonical service tables/cursor; appends recovery audit; preserves telemetry/audit history | Intake paused; signed snapshot ID obtained | Creates the clean base required for deterministic experiment/replay. |
| `recovery.reconcile(plan)` | Current selected state and candidate behavior | Appends compensation/reconciliation records; never deletes accepted history | Intake paused; candidate or safe revision active | Alternative to snapshot restore; must satisfy same final roots and invariants. |
| `release.rollback(revision)` | Available revision roots | Activates `r0` code/config; appends deployment audit | Intake paused | Neutralizes `r1` so diagnostic replay does not inherit attempt-budget loss. |
| `release.deploy(candidate_root)` | Candidate root/config | Activates candidate; records deployment and canary pending | Intake paused; candidate exists | Public verification executes candidate, not workspace-only code. |
| `runtime.run(workload, cutpoint)` | Public workload definition, active revision, current state, fake scheduler | Advances tick; may append journal/effects/cursor/keys/logs/traces/workload receipt | Intake paused for diagnostic cutpoint runs; candidate active for verification | Creates the evidence artifacts or verification state that later tools/grader read. |
| `recovery.resume` | Intake, deployment health, public receipts, recovery provenance | Opens intake; appends audit event | Candidate deployed; recovery provenance exists; required public checks pass | Final health/incident evaluation requires intake open. |
| `oracle.evaluate` | All canonical state, hidden workloads/adapters, audit roots | Runs hidden workloads on isolated verifier clone; emits reward receipt | Episode submitted | Privileged final grading only; never callable or inspectable by agent. |

## 7. The minimum tool set separates code, telemetry, durable state, execution, recovery, and release

| Tool | Inputs | Outputs | Visibility | State preconditions and transition | Unique information | Why another tool cannot replace it | Leakage risk and control |
|---|---|---|---|---|---|---|---|
| Release tool | `status`; `rollback(revision)`; `deploy(candidate_root)` | Revision/config roots, intake/canary status, deployment receipt | Agent-visible | Rollback/deploy require paused intake and change active revision | Which code/config is actually executing | Workspace only shows files; runtime only shows behavior | Must not expose member label or gold root; neutral revision labels only. |
| Workspace tool | `read(path)`; `edit(patch)` | One file or patch receipt/candidate root | Agent-visible | Edit changes candidate only; no runtime effect until deploy | Contract and stage implementation | Telemetry/state do not reveal source logic | Filenames/comments/diff are byte-identical across pair and neutral. |
| Log tool | Alias + bounded tick window | Normalized lines and correlation handle | Agent-visible | Read-only; requires existing incident/workload | Temporal symptom-to-handle mapping | Trace requires the handle; state lacks temporal component messages | Log templates must be matched and omit IDs before explicit correlation. |
| Trace tool | Correlation handle | Ordered spans with neutral stage IDs and internal selectors | Agent-visible | Read-only | Cross-component lineage and attempt/restart structure | Logs omit lineage; state omits temporal span order | Stage names are ordinal, not causal labels. |
| State tool | Selector + one view (`journal`, `progress`, `effects`, `keys`, `recovery`) | Bounded canonical rows/root summaries | Agent-visible, read-only | Requires selector or public stream; never writes | Durable facts and signed recovery availability | Trace cannot prove committed rows; release cannot inspect data | No unrestricted dump; outputs never include member selector, hidden workloads, or oracle fields. |
| Runtime tool | Public workload ID, public inputs, optional neutral cutpoint | Workload receipt, tick range, log alias | Agent-visible | Diagnostic cutpoint run requires paused intake; mutates the isolated service state deterministically | Counterfactual experiment and executable verification | Static tools cannot create the distinguishing state | Cutpoint names map only to public stage ordinals; no “crash-after-effect” labels. |
| Recovery tool | `pause`; `restore(snapshot)`; `reconcile(plan)`; `resume` | Signed transition receipt and resulting roots | Agent-visible | Enforces real consistency preconditions; changes intake/persisted state/audit | Authorized safe restoration or equivalent recovery | Direct DB writes are forbidden; release changes code, not data | Snapshot names are opaque; restore cannot reveal precomputed gold state beyond signed roots. |
| Oracle/verifier | Episode state and hidden clone | Predicate and reward receipt | Privileged only | Runs after submit | Hidden counterfactual and tamper truth | No agent tool has hidden definitions or member selector | Separate identity/path; receipt exposes predicate IDs, not hidden inputs. |

There is deliberately no all-in-one “diagnose” call. The log → trace → state selector chain is load-bearing: logs locate a run, traces expose lineage selectors, and state views establish what became durable.

## 8. Causal action analysis passes the 15-action gate without counting overhead

### Labels

- **CAUSALLY NECESSARY (C):** changes world state required for a valid final state or for safe experimentation.
- **INFORMATION-GATHERING NECESSARY (I):** supplies a fact unavailable from prior observations and needed to choose or locate the repair.
- **VERIFICATION NECESSARY (V):** establishes a required public behavior before safe resume/submission.
- **INTERFACE OVERHEAD (O):** syntax, polling, paging, declarations, or mechanical navigation. These are excluded.
- **OPTIONAL:** a valid but non-minimal action. These are excluded.

### A. Shortest path when the latent cause is already known

This path is intentionally shorter. It demonstrates that task length comes from causal discrimination, not a forced checklist.

| # | Action | Label | Later dependency |
|---:|---|---|---|
| 1 | Read active revision/status. | I | Recovery and deployment must target the actual active roots. |
| 2 | Read the inherited `r0 → r1` config change. | I | Candidate must restore canonical retry semantics. |
| 3 | Inspect incident state and obtain signed `S0`. | I | Restore cannot use a guessed snapshot ID. |
| 4 | Pause intake. | C | Rollback/restore cannot be safe with concurrent journal writes. |
| 5 | Roll back `r1` to `r0`. | C | Removes the attempt-budget regression before replay. |
| 6 | Restore `S0`. | C | Removes excess persisted effect while preserving accepted-history provenance. |
| 7 | Read the known causal module/stage implementation. | I | Locates a valid edit against the current source. |
| 8 | Apply the candidate repair and canonical config. | C | Creates the candidate behavior. |
| 9 | Deploy the candidate. | C | Public workloads must execute the candidate. |
| 10 | Run P1. | V | Proves routine redelivery does not duplicate. |
| 11 | Run P2. | V | Proves retry support and no loss. |
| 12 | Run P3. | V | Proves required feature and public compatibility. |
| 13 | Resume intake. | C | Final service must be available, not merely quiescent. |
| 14 | Read final health/status. | V | Confirms deployed root, intake, and public receipts before submit. |

**Known-cause minimum: 14 genuine actions: 10 causal/information and 4 verification.** No claim is made that the repair itself is intrinsically 15 actions.

### B. Shortest realistic path when the cause is unknown: Instance A if the relay experiment is tried first

| # | Action | Label | Later action or observation that depends on it |
|---:|---|---|---|
| 1 | `release.status`. | I | Establishes `r1` and open intake; recovery targets are otherwise unknown. |
| 2 | Read `contract.md` and public resource/occurrence constraints. | I | Prevents coarse dedupe and defines compatibility verification. |
| 3 | Read the inherited revision/config diff. | I | Establishes the retry regression and canonical budget. |
| 4 | Query initial logs by public alias/window. | I | Produces the only valid correlation handle for the incident trace. |
| 5 | Query the initial trace. | I | Produces neutral stage lineage and selectors required by state inspection. |
| 6 | Inspect correlated journal/effect/progress state and obtain `S0`. | I | Confirms persisted excess effect, preserves ambiguity, and supplies recovery token. |
| 7 | Read the intake stages in `flow.py`. | I | Identifies the `s2/s3` candidate boundary and its diagnostic cutpoint. |
| 8 | Read the relay/effect stages in `flow.py` and `store.py`. | I | Identifies the `s5/s6` boundary and shows why an event marker alone is non-atomic. |
| 9 | Pause intake. | C | Required before revision and state restoration. |
| 10 | Roll back `r1` to `r0`. | C | Diagnostic execution must not retain the one-attempt regression. |
| 11 | Restore signed `S0`. | C | The cutpoint experiment needs clean deterministic state and no pre-existing excess effect. |
| 12 | Run one command with neutral cutpoint `s5.exit`, then restart. | C + I | Creates the discriminating run; later telemetry/state do not exist without it. |
| 13 | Query its logs. | I | Produces the new run's trace handle. |
| 14 | Query its trace. | I | Reveals one intake/event identity across two relay epochs and supplies state selectors. |
| 15 | Inspect its journal/effect/progress state. | I | Proves one event produced two effects across the `s5/s6` gap, selecting A's repair layer. |
| 16 | Edit a valid worker/store repair and canonical retry config. | C | Creates the candidate selected by evidence. |
| 17 | Deploy the candidate. | C | Verification and final state must use it. |
| 18 | Run P1. | V | Routine same-event redelivery correctness. |
| 19 | Run P2. | V | Required retry/no-loss behavior. |
| 20 | Run P3. | V | Feature and public compatibility. |
| 21 | Resume intake. | C | Required availability state. |
| 22 | Read final health/status. | V | Confirms candidate root, intake, and public receipts. |

**Instance A realistic path: 22 genuine actions.** Eighteen are causal or information-gathering; four are verification. There are zero overhead/optional actions.

### Instance B under the same pair-blind experiment policy

Because early evidence and source layout are matched, a pair-blind deterministic policy cannot know which boundary to test first. If it tests `s5.exit` first, B needs four additional actions after step 15:

| Added step | Action | Label | Dependency |
|---:|---|---|---|
| 16 | Run the same command with cutpoint `s2.exit`, then retry it. | C + I | Creates the intake-boundary counterfactual after the relay experiment was negative. |
| 17 | Query new logs. | I | Produces the trace handle. |
| 18 | Query new trace. | I | Reveals two intake/event identities and no relay replay. |
| 19 | Inspect journal/key/effect state. | I | Proves one command occurrence produced two event identities, selecting B's repair layer. |

The edit/deploy/verification/resume actions then shift to steps 20–26.

**Instance B under this policy: 26 genuine actions: 22 causal/information and four verification.** If the intake experiment is chosen first, B is 22 and A is 26. With an equal prior over the matched pair, the pair-blind expected gold length is **24 actions**, with a **22–26** range.

### Long-horizon gate

**PASS.** The conservative lower member has 18 causally or informationally necessary actions, exceeding the required 15 without counting verification, polling, formatting, repeated paging, declarations, waits, phase locks, retries caused by tool syntax, or no-ops. The known-cause path remains 14, which is desirable evidence that the extra length is specifically the cost of safe causal discrimination and recovery.

## 9. The final-state verifier grades behavior, state, and provenance

### Strict predicates

| ID | Predicate | Implementation-independent definition | Primary shortcut blocked |
|---|---|---|---|
| P1 Incident resolved | All member-specific hidden incident workloads produce their expected semantic outcome and no incident alert is derived from canonical state. | Visible-only symptom suppression. |
| P2 Safe recovery | Either signed `S0` restoration or a forward reconciliation proves the same accepted-occurrence set and correct net-effect root, with audit provenance. | Patch future code while leaving corrupt past state. |
| P3 No event loss | Every accepted occurrence in the verifier workload history has exactly one required settled net effect unless the contract marks the command as an idempotent retry of the same occurrence. | Retry reduction, exception swallowing, data deletion. |
| P4 No duplicated side effects | Net positive effects equal one per semantic occurrence; compensation is allowed only when linked to an excess effect and results in net one. | Retry inflation, non-atomic marker, duplicate journal acceptance. |
| P5 Feature enabled | Intake and settlement delivery are enabled; all public and hidden required occurrence classes remain processable. | Feature flag off, worker stopped, route disabled. |
| P6 Persisted-state integrity | Cursor is the maximum contiguous settled sequence; command mappings are total/unambiguous; no orphaned intents/marks; effect provenance links to accepted journal lineage. | Direct mutation, partial repair, stale cursor. |
| P7 Retry behavior | Attempt budget equals 3 and one pre-effect transient failure recovers without loss or duplication. | Continue inherited remediation, stale `r1`, swallow error. |
| P8 Repeat-occurrence compatibility | Legitimate distinct occurrences sharing a business key remain distinct and settle once each. | Coarse business-key dedupe, unconditional joint fix. |
| P9 Deployment state | Active root is the submitted candidate; public receipts were produced by that root; intake is open; health is green. | Workspace-only edit, stale-version pin, stopped service. |
| P10 Canonical configuration | Attempt budget 3, transient behavior retry, settlement and intake enabled; unrelated public configuration values preserved. | Retry inflation, config weakening, feature disable. |
| P11 Deterministic resource contract | Newly accepted occurrences consume at most four durable state mutations and complete within the declared fake-tick budget. | Unconditional application of both coordination stacks, runaway retry/over-repair. |
| P12 Tamper resistance | Public/hidden workload roots, source-of-truth audit chain, signed snapshots, verifier files, and agent-visible permissions match canonical roots; direct DB edits lack valid audit transitions. | Test editing, workload modification, DB mutation, oracle import. |

### Pair-specific semantics

- **A:** H-A1 must show one net effect despite interruption between `s5` and `s6`; H-A2 must preserve two legitimate occurrences with a shared business key.
- **B:** H-B1 must show one accepted journal identity/net effect after a response timeout and retry of the same command occurrence; H-B2 must show no ambiguous command-to-event lineage.

### Reward buckets

| Bucket | Weight | Full-credit rule |
|---|---:|---|
| Incident resolution | 0.20 | P1 true. |
| Delivery correctness | 0.30 | P3, P4, and P7 true. |
| Persisted integrity | 0.20 | P2 and P6 true. |
| Feature/compatibility | 0.10 | P5 and P8 true. |
| Deployment/config/resource | 0.15 | P9, P10, and P11 true. |
| Tamper resistance | 0.05 | P12 true. |

**Strict pass requires all predicates, not merely total reward 1.0 after averaging.** A predicate failure zeros its bucket. Fatal tamper makes strict pass false regardless of other buckets. Public workload results are feedback, not independent correctness reward.

### Why the reference patch is not an oracle

The verifier does not inspect which module changed, whether an outbox table exists, whether a unique constraint was used, or how many lines/files were edited. It observes workload semantics, canonical persisted relationships, deployment/config state, resource bounds, and audit integrity. Patch breadth may be reported diagnostically but is not scored.

## 10. Two structurally different valid repairs for Instance A

### Valid solution A1: atomic intent plus progress

1. During relay handling, atomically create a stable settlement intent for the source event and advance progress in one SQLite transaction.
2. A dispatcher converts each intent to an effect using the intent ID as the stable effect identity.
3. Restart after `s5` sees either neither transaction result or both; an existing intent cannot be duplicated.
4. Retry policy is restored to canonical three attempts.

This changes the worker/store transaction boundary and may introduce/use `intents`. It satisfies P1–P12 within the mutation budget because intent creation and progress update share one durable transaction and dispatch uses an existing stable identity.

### Valid solution A2: idempotent effect ledger with stable effect identity

1. Keep relay progress separate.
2. Derive a stable effect identity from the semantic occurrence/source event.
3. Make ledger insertion conditional/unique on that identity, returning the existing committed effect on replay.
4. Advance progress after the ledger confirms the stable effect.
5. Restore canonical retry behavior.

This changes the effect boundary rather than introducing an atomic intent/progress design. Interruption after effect but before progress causes replay, yet replay observes the same effect identity and cannot add a second net effect. It also satisfies P1–P12.

### Why both score 1.0

Both preserve every accepted occurrence, produce one net effect, recover from all declared cutpoints, preserve repeated legitimate occurrences, retain retry support, maintain cursor/provenance integrity, meet the same mutation/tick budget, and leave a healthy candidate deployment. The verifier has no predicate that distinguishes their architecture.

### Instance B valid repair family

For completeness, B may use either an atomic `journal + command_key` transaction or stable event identity reuse derived from `(command_key, occurrence_id)`. These are also implementation alternatives, though only two alternatives for one instance were required.

## 11. The familiar wrong solution passes public feedback and fails for different hidden reasons

### Wrong strategy

The agent follows the inherited diagnosis but makes it appear safer:

1. restore `attempt_budget` from 1 to 3;
2. add `event_marks(event_id)` in the relay;
3. on routine redelivery, skip an event whose mark exists;
4. write the mark *after* the effect succeeds;
5. deploy and run P1–P3.

This is locally reasonable. It recognizes that retry must remain enabled, uses an event identity rather than a public alias, and passes all public workloads:

- P1: the routine requeue occurs after the first path has written the mark, so the duplicate is skipped.
- P2: failure happens before effect/mark; retry succeeds and writes both.
- P3: unique events each receive their own mark and effect.

### Different hidden failures

- **A:** H-A1 interrupts after the effect but before the mark. Restart sees no mark, replays the same event, and adds a second effect. Hidden evidence is **one event identity, two relay epochs, two effects, mark/progress gap**.
- **B:** H-B1 times out before command-key registration and creates two event identities. Each identity is processed once and marked once, yielding two effects. Hidden evidence is **one command occurrence, two intake spans, two journal identities, one effect per identity**.

### Expected reward buckets

| Bucket | A wrong solution | B wrong solution | Reason |
|---|---:|---:|---|
| Incident resolution (0.20) | 0 | 0 | Member-specific hidden incident remains. |
| Delivery correctness (0.30) | 0 | 0 | A duplicates on crash; B duplicates on command retry. |
| Persisted integrity (0.20) | 0 | 0.20 | A leaves effect/mark/progress inconsistency; B's per-event state is internally consistent even though command lineage is semantically wrong. |
| Feature/compatibility (0.10) | 0.10 | 0.10 | Required public/repeat behavior remains enabled for this specific marker strategy. |
| Deployment/config/resource (0.15) | 0.15 | 0.15 | Candidate deployed; retry restored; budget met. |
| Tamper resistance (0.05) | 0.05 | 0.05 | No tampering. |
| **Total / strict** | **0.30 / fail** | **0.50 / fail** | Public feedback passes on both; hidden causal behavior separates them. |

## 12. Shortcut battery

| Strategy | Public expectation | Predicate outcome A | Predicate outcome B | Required verifier decision |
|---|---|---|---|---|
| Untouched state | Existing canary may look green once | Fails P1–P4, P7, P9–P10 | Same | Reject; expected reward below 0.20 because delivery/config/recovery remain invalid. |
| Continue inherited remediation | May suppress a routine retry | Fails P2–P4, P7, P10 | Fails P1–P4, P7, P10 | Reject: accepted transient work is lost and causal fault remains. |
| Blanket revert to `r0` | Restores attempts | Fails P1/P4 under H-A1 and P9 | Fails P1/P4 under H-B1 and P9 | Reject: original fault returns and no candidate deployment. |
| Feature disable | Duplicate disappears | Fails P5, P8, P9–P10 | Same | Reject. |
| Retry inflation | May eventually settle | Fails P4, P10–P11; can amplify A replay | Fails P4, P10–P11; does not collapse B event identities | Reject. |
| Exception swallowing | Visible logs quiet | Fails P3, P5, P7 | Same | Reject for loss/disabled recovery. |
| Direct state-database mutation | Can make counts look correct | Fails P2, P6, P12 | Same | Reject; no signed recovery/audit transition. |
| Data deletion/truncate | Removes duplicate | Fails P2–P3, P6, P12 | Same | Reject; accepted history/effects lost. |
| Hard-coded public request/alias IDs | P1 may pass | Fails P1, P3–P4 under regenerated hidden IDs | Same | Reject. |
| Workload/test modification | Could falsify public receipt | Fails P12; hidden roots external | Same | Fatal reject. |
| Stale-version pinning | Could avoid one active path | Fails P1, P7, P9–P10 | Same | Reject. |
| Broad joint over-repair, unconditional | Public likely passes | Fails P8 or P11 under repeat-occurrence/resource workload | Fails P11 unless implementation shares coordination within budget | Reject as a universal shortcut; it cannot pass the pair blindly. |
| Contract-aware generalized repair within budget | Public passes | May pass all | May pass all | **Accept** if all predicates pass; this is a valid generalized solution, not a hack. |
| Alternate correct A1 | Passes | P1–P12 all true | Not the designated B solution; may fail B if it omits intake repair | Full 1.0 on A. |
| Alternate correct A2 | Passes | P1–P12 all true | Not the designated B solution; may fail B if it omits intake repair | Full 1.0 on A. |
| Valid B atomic acceptance repair | Passes | Does not fix A's H-A1 | P1–P12 all true | Full 1.0 on B only. |

### Broad-fix conclusion

The verifier cannot and should not reject a behaviorally correct, resource-compliant generalized design merely because it repairs both potential boundaries. The important condition is that a blind additive “apply both textbook fixes” patch is not dominant: it either breaks repeat-occurrence behavior or exceeds the public contract's deterministic mutation budget. Passing both members requires a genuinely integrated design that preserves the same semantics and resource bound, which is legitimate engineering rather than reward hacking.

## 13. Ablations make each claimed property falsifiable

Counts below are **PREDICTIONS**, not measurements. Baseline success means success of naive or familiar-wrong policies, not a specific frontier-model percentage.

| Ablation | Predicted realistic gold count | Baseline-success change | Shortcut-success change | Claimed capability that disappears |
|---|---:|---|---|---|
| Full pair | 22 if first experiment matches; 26 otherwise; expected 24 | Reference | Familiar wrong passes public, fails hidden | Full provisional construct |
| Remove inherited failed remediation (`r0` active, clean state) | 18 / 22; expected 20 | Increases: no retry regression or persisted excess effect to recover | Blanket “just patch cause” becomes valid; rollback shortcuts irrelevant | Recovery from an already-applied remediation |
| Remove misleading/matched early evidence and expose event-lineage shape in initial logs | 18 for each member | Increases: correct experiment can be selected immediately | Decoy-following and wrong marker rates should drop | Deceptive evidence and matched-pair discrimination |
| Reveal true cause immediately | 14 | Strong increase | Familiar wrong should disappear if agent follows supplied cause | Active causal discovery; task becomes ordinary known-cause repair |
| Remove safe-state restoration/equivalent recovery requirement and reset state automatically | 19 / 23; expected 21 | Increases | Future-only patches and blanket data reset succeed | Stateful recovery and accepted-history preservation |
| Replace log, trace, state, and source reads with one complete diagnostic dump | 16 / 16 | Increases substantially | Mega-dump localization succeeds; evidence-routing mistakes disappear | Heterogeneous non-interchangeable information gathering |
| Remove hidden counterfactual workloads | Agent-visible path count unchanged; grader work reduced | Apparent success rises | Familiar wrong, hard-coded IDs, retry suppression, and joint over-repair can pass | Difficulty by construction and implementation-independent semantic verification |
| Allow direct canonical-state editing with no signed audit requirement | Approximately 10–12 | Apparent success rises sharply | Direct DB mutation/data deletion become dominant | Tamper resistance and genuine recovery |

### Ablation pass criteria for the implementation spike

1. Removing inherited remediation must reduce the minimal valid path by at least three actions and make a future-only repair valid.
2. Revealing the true cause must reduce the path to the 14-action cause-aware path.
3. A complete diagnostic dump must remove at least the log → trace → state chain and eliminate the two-experiment worst case.
4. Removing hidden workloads must cause the familiar wrong solution to receive strict pass, proving those workloads are load-bearing.
5. Allowing direct state editing must make at least one mutation shortcut pass, proving P12 is necessary.

If these effects do not occur in deterministic control scripts, the corresponding construct claim is decoration and the candidate returns to HOLD or pivots.

## 14. A one-week spike is credible only for this hand-authored pair

### Mandatory implementation: five to seven focused days

| Day | Mandatory deliverable | Completion evidence |
|---:|---|---|
| 1 | Single-process service skeleton, SQLite schema, fake tick scheduler, neutral source layout, `r0/r1`, and signed `S0` for both members. | Deterministic re-run produces identical initial roots and matched visible artifacts. |
| 2 | Agent-visible release/workspace/log/trace/state/runtime/recovery interfaces with bounded outputs and no mega-dump. | Tool contract table matches implementation; pair selector absent from agent-visible probes. |
| 3 | Public P1–P3 and hidden A/B/shared workloads; predicate verifier P1–P12; reward receipt. | Gold state and untouched state produce expected predicate vectors. |
| 4 | Gold A1, gold A2, one valid B repair, familiar wrong solution, blanket revert, inherited continuation, feature disable, direct mutation, and data deletion controls. | A1/A2 strict pass A; B repair strict pass B; shortcuts fail named predicates. |
| 5 | Remaining shortcut controls, broad joint over-repair, fixture-root/tamper checks, alternative recovery route, and causal-action receipts. | Cheat battery and 22/26 path receipts are reproducible. |
| 6–7 buffer | Leak audit, false-accept/false-reject fixes, ablation controls, documentation, and rerun from a clean workspace. | One command regenerates receipts; known limitations recorded. |

### Optional within the week only if mandatory gates are green

- A third hand-authored history per member using different aliases and journal positions.
- One contract-aware generalized repair to prove the verifier accepts an integrated alternative.
- One or two frontier-agent smoke runs to confirm agents reach the intended decision point.
- Read-only process/filesystem probes beyond the minimum oracle separation checks.

### Explicitly deferred

- Procedural generation beyond regenerated identifiers and histories.
- 12–20 seeds or statistical calibration.
- Production-grade containers, Kubernetes, real network faults, GUI tooling, or cloud APIs.
- Large-scale model comparison, pass-rate claims, confidence intervals, or RL training.
- Multiple incident families, languages, databases, or deployment topologies.
- Perfect sandbox isolation; the spike must demonstrate separation under the local agent identity but may document stronger isolation as later work.

### Feasibility judgment

**DESIGN CLAIM:** one hand-authored pair, three gold repairs, one familiar wrong repair, and the required shortcut/ablation controls are credible in five to seven days if the substrate stays single-process and the implementation optimizes for verifier evidence rather than realism. A generator, model study, or production isolation would make the plan non-credible.

## 15. Final decision

### Gate review

| GO requirement | Result | Reason |
|---|---|---|
| Defensible novelty distinction | Pass, narrowly | Residual distinction is the matched already-remediated code/state pair with active causal experiments and alternative behavioral repairs; remediation generally is not novel. |
| Paired design with different causal repairs | Pass | A repairs effect/progress recovery; B repairs intake acceptance/idempotency. |
| Implementation-independent verifier | Pass in design | P1–P12 grade semantics, state, resource contract, deployment, and tamper roots, never a reference diff. |
| Two valid solutions accepted in principle | Pass | A1 atomic intent/progress and A2 stable idempotent effect both satisfy identical predicates. |
| Familiar wrong rejected by hidden behavior | Pass | Public passes both; H-A1 and H-B1/H-B2 fail for different provenance. |
| No dominant broad shortcut | Pass with caveat | Blind joint hardening fails repeat-occurrence/resource behavior; an optimized generalized solution is valid, not a shortcut. |
| At least 15 genuinely necessary actions | Pass | Lower realistic path has 18 causal/information actions; expected pair-blind path is 24 total. |
| Credible one-week scope | Pass only at pair scale | Mandatory plan excludes generator, production infrastructure, and model calibration. |

### Decision rationale

Candidate 1 should be **retained**, but only under the observable stateful-repair wording in Section 1. It should not return to the broader “internal hypothesis revision” framing. The next step is not full environment construction; it is the bounded verifier implementation spike described in Section 14. Failure of the alternative-solution, shortcut, leak, action-count, or ablation receipts should immediately return the candidate to HOLD and trigger a pivot to the cross-artifact causal-repair fallback.

GO TO VERIFIER IMPLEMENTATION SPIKE
