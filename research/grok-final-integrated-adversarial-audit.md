# Final integrated adversarial audit

**Auditor role:** independent, read-only, falsify-by-default  
**Date:** 2026-07-12  
**Trial repository:** `C:\project-bussiness\frontier-final-integration`  
**APEX-SWE checkout:** `C:\project-bussiness\apex-swe`  

## Executive verdict

**FAIL**

The environment has a working core path: twelve-tool gateway, pair-matched public workspaces, S0 restore, and member-hidden workloads that still require a real idempotent `flow.py` to reach score `1.0` via `effect_exists`. That is not enough for the claimed final contract.

Executable attacks falsify or leave unverified load-bearing claims: final source-commit binding, receipt adequacy, reward-ladder completeness, two structurally different valid repairs, ≥15-action pair-blind horizon, Gymnasium `check_env`, and real APEX-SWE harness execution. Docker isolation is **NOT VERIFIED**. Passing 84 pytest cases does not rescue these gaps.

## Exact audited commits

| Item | Value |
|---|---|
| Branch | `integration/final-build` |
| Initial HEAD (receipt tip) | `70b7a64e8dfde212e278e6c9672c677c94d6edd6` |
| Stated source commit | `065dfdb2ff63243b960ab4011735776a89888680` |
| Stated receipt commit | `70b7a64e8dfde212e278e6c9672c677c94d6edd6` |
| Both on `origin/integration/final-build` | **YES** |
| Receipt descends from source | **YES** (`merge-base --is-ancestor` exit 0) |
| Receipt diff vs parent | **only** `evidence/final-environment.json` (2 insertions / 2 deletions) |
| Committed receipt `tested_source_commit` | `065dfdb2ff63243b960ab4011735776a89888680` (not self) |
| APEX-SWE pin | `7cfa580dd59704ff15cf558bda80257c23b6cb04` on `main`, clean |
| Trial tree at start | clean |
| APEX tree at start | clean |

Initial record commands confirmed the above before any probes.

## Reproduction table

| Suite / command | Result | Duration | Notes |
|---|---|---|---|
| `pytest tests/milestone_1 -q` | **27 passed** | ~19.2s / wall ~22.7s | OK |
| `pytest tests/milestone_2 -q` | **34 passed** | ~33.9s / wall ~36.7s | OK |
| `pytest tests/final_core -q` | **2 passed** | ~0.53s | Thin |
| `pytest tests/soundness -q` | **4 passed** | ~0.58s | Thin |
| `pytest tests/controls -q` | **4 passed** | ~3.17s | Thin vs claimed control battery |
| `pytest tests/adapters -q` | **12 passed** | ~2.66s | OK |
| `pytest tests/integrations -q` | **1 passed** | ~0.98s | Internal adapter only |
| `pytest tests -q` | **84 passed** | ~63.5s / wall ~65.9s | Matches README count |
| `verify_final_environment.py → %TEMP%\final-audit-1.json` | exit 0 | ~84s (pair) | Binds **HEAD = receipt tip**, not source |
| `verify_final_environment.py → %TEMP%\final-audit-2.json` | exit 0 | (same run) | Semantically equal to audit-1 after timestamp strip |
| `training_ground.cli run-scripted --split eval --seed 0` | exit 0 | — | Score 1.0 JSON |
| `training_ground.cli list-instances --split eval --count 5` | exit 0 | — | Matches receipt IDs |
| `scripts/smoke_apex_scripted.py` | exit 0 | — | **PASSED** on public `ScriptedRecoveryPolicy` (no flow repair) |
| `scripts/smoke_apex_docker.py` | **NOT RUN** | — | Docker daemon unavailable |
| Gymnasium `check_env` | **FAIL** | — | Obs not in declared space |
| Upstream `apx run` / harness | **NOT VERIFIED** | — | No apex-swe venv; no paid model calls |

### Receipt comparison

| Check | Result |
|---|---|
| Temp1 vs Temp2 byte equality | **False** (timestamps differ) |
| Temp1 vs Temp2 semantic equality (timestamp excluded) | **True** |
| Temp vs committed semantic `verification` | **True** |
| Temp vs committed `tested_source_commit` | **False** — regen writes `70b7a64…`; committed has `065dfdb…` |
| Roots / scores / instance IDs / test_count | Present and equal in `verification` block |
| Omitted evidence vs final-build contract | **Nearly all promised matrices absent** (see §19) |

## Receipt / source-binding review

Inspected `scripts/verify_final_environment.py` and `scripts/verify_common.py`.

| Probe | Result |
|---|---|
| `--source-commit` flag | **Absent** |
| Uses `validate_source_commit` | **No** (unlike M1/M2 verifiers) |
| Binding rule | `git rev-parse HEAD` only |
| Regen at receipt tip | Labels `tested_source_commit = 70b7a64…` (receipt itself) |
| `validate_source_commit(None, allowed=[final-environment.json])` | Would correctly walk past receipt-only tip to `065dfdb…` — **but final script never calls it** |
| Arbitrary / nonexistent / blob SHA handling in final script | **None** — no validation path |
| Dirty tree / dirty tests / extra untracked evidence | **Not checked** by final script |
| Fail closed | **No** — succeeds and writes a pass receipt while mis-binding HEAD |

**CRITICAL:** The final evidence entrypoint can label an unrelated or receipt-only tip as the tested source. The committed receipt happens to name `065dfdb…`, but that property is not enforced by the current final verifier and is not reproducible at the receipt tip with the shipped script.

## Contract traceability matrix

| Requirement | Implementation | Direct test | Live verifier evidence | Receipt evidence | Status |
|---|---|---|---|---|---|
| Episode API (`reset/step/close/grade`) | `training_ground/episode.py` | `tests/final_core` (2) | Auditor probes | scores only | **PARTIALLY VERIFIED** |
| Deterministic reset | gateway + fixture build | M1 determinism | same-seed roots equal | none | **PARTIALLY VERIFIED** (`reset(seed=)` ignored) |
| Manifests / splits | `manifests.py` | list-instances | auditor | instance_ids | **VERIFIED** |
| Hidden workloads | `runtime.py` + `workloads.py` | soundness/controls | auditor grades | **missing counts** | **PARTIALLY VERIFIED** |
| Strict reconstruction | `verifier.py` fresh fixture copy + S0 | soundness | auditor | missing | **PARTIALLY VERIFIED** |
| Mandatory predicates | `predicates.py` / `reward.py` | thin | ablations | missing | **CONTRADICTED** (several non-load-bearing) |
| Reward ladder | `reward.py` | none dedicated | unit + live | missing | **PARTIALLY VERIFIED** |
| ≥2 valid repair families | `policies.IDEMPOTENT_FLOW` only | controls:1 | intent/mark alts **fail** | missing | **NOT VERIFIED** / **CONTRADICTED** |
| Wrong controls battery | `tests/controls` (4) | partial | auditor partial | missing | **PARTIALLY VERIFIED** |
| Cheat battery + exploit flags | mostly absent | leak_probe only | auditor | missing | **NOT VERIFIED** |
| ≥15 pair-blind horizon | `valid_repair_policy` length 14 | none | measured 13 executed | missing | **CONTRADICTED** |
| Deterministic evidence | verify script | regen | auditor | thin | **PARTIALLY VERIFIED** |
| Gymnasium | `training_adapters/gym_env.py` | adapters | `check_env` FAIL | gym_reward only | **PARTIALLY VERIFIED** |
| APEX-SWE | task pack + side-car smokes | 1 integration test | no `apx` | **absent** | **NOT VERIFIED** (compat packaging only) |
| Container boundary | Dockerfile/compose text | none live | Docker down | absent | **NOT VERIFIED** |

## Episode API attack results

| Attack | Outcome |
|---|---|
| Step before reset | Rejected: `EnvironmentError: environment is not reset` |
| Repeated reset same work_dir after close | **FAIL** — gateway `FileExistsError` on fixture mkdir (`exist_ok=False`) |
| Reset with new work_dir after close | Works |
| `reset(seed=999)` | **Does not change instance**; manifest fixed at construction |
| Deterministic same-seed | Score/predicates/roots equal across 3 processes |
| Close idempotent | Yes |
| Step after termination | Allowed; remains terminated; reward 0 |
| Step after truncation | Allowed; remains truncated |
| Grade after truncation | Returns score 0.0 |
| Grade before termination | Allowed (partial progress) |
| Repeated grade | Cached result |
| Action / byte / tick limits | Truncation enforced via `Limits` + `max_steps` |
| Malformed / unknown tool | Error obs; not terminated |
| `arguments: []` | **Silently coerced to `{}`** because `action.get("arguments") or {}` treats `[]` as falsy |
| Extra action fields | Ignored (not rejected) |
| Gateway failure / child death | Reset-after-reuse surfaces as gateway start failure |
| Terminated vs truncated | Distinct flags observed |
| Leak in obs/info (profile, fixture DB, authority, predicates) | Not in sanitized obs / public manifest |
| `step` `info["response"]` | Full raw tool result (unsanitized) |

Twelve tools confirmed in inventory.

## Pair-blindness and split results

| Check | Result |
|---|---|
| Public workspace digests A vs B (forced profiles, seeds 0/1/7) | **Byte-identical** for all five service files |
| Public manifests equal under profile override | Yes |
| Stripped observations equal | Yes |
| Profile in public manifest / reset info | Absent |
| Train/dev/eval instance-ID overlap (sampled) | None observed |
| Split seed namespaces | Offsets 0 / 1e9 / 2e9 — no overlap |
| Profile from `sha256("profile-{effective_seed}") % 2` | **Fully inferable** if `SPLIT_OFFSETS` known (public in `manifests.py`) |
| Same seed → same public package across processes | Yes |
| Fixture/member via agent-visible status blob | No sqlite/fixture/authority strings observed |
| Hidden workload via `runtime.run("H-A1")` | Rejected (`unknown_workload` / pause gates) |

**MAJOR caveat:** pair member is algorithmically recoverable from split+seed using committed public code. This is not an observation leak, but it weakens “pair-blind” claims for any agent that can read the environment package.

## Strict reconstruction analysis

Authoritative grading inputs (`Verifier.grade`):

1. Fresh **copy** of `fixture_dir/service.sqlite3`
2. Live **session** `active/` and `candidate/` trees (not a sealed candidate blob)
3. Caller-supplied `transcript` list
4. Privileged `profile` + `RecoveryAuthority`
5. Hidden workloads executed in-process on restored S0 + active workspace code

| Attack | Result |
|---|---|
| Empty transcript + good files | score 0.0 (`initial_investigation` false) |
| Fabricated 2-step diagnostic transcript + good files | **score 1.0** |
| Revert active/candidate code without transcript change | score drops (member fails) — live trees trusted |
| Fixture `effects` DELETE before grade | score 1.0 (S0 restore repairs) |
| Forged `metadata.json` session_id | score 1.0 |
| Cross-profile grade (A session, profile=1 authority) | score 0.0 (auth/recovery path) |
| Hidden replay | **Yes** — workloads run on restored copy |

**CRITICAL:** Transcript content is not bound to session digests. Tool *names* alone satisfy investigation predicates. Combined with deployed candidate files, a forged transcript yields full credit at the `Verifier` API. `IncidentEnv` builds transcripts internally, so ordinary tool-surface agents cannot forge them — but any adapter/harness that accepts external transcripts, or any privileged caller, can.

`state_root_integrity` is **not** a comparison against an expected post-repair root; it is `audit_chain_valid ∧ snapshot_valid ∧ recovery_proof`.

## Predicate matrix

| Predicate | How set | Default stay? | Executed evidence? | Mandatory for 1.0? | In final receipt? |
|---|---|---|---|---|---|
| `valid_episode` | dirs exist | no | weak | yes (else 0) | no |
| `protocol_abuse` | **never assigned** | stays False | **no** | only if True→0 | no |
| `state_tampering` | `not state_root_integrity` | — | derived | yes if True→0 | no |
| `initial_investigation` | any tool name in transcript | — | name-only | yes | no |
| `diagnostic_evidence` | logs/trace/inspect names | — | name-only | yes (else 0.10) | no |
| `authenticated_recovery` | audit+snapshot+proof | — | yes | yes | no |
| `candidate_prepared` | four files exist | — | existence only | yes | no |
| `public_workloads_pass` | P1–P3 outcome | — | **partial** (call success, not DB effects) | yes | no |
| `shared_hidden_workloads_pass` | H-TRANS/S1/S2 | — | mixed | yes | no |
| `member_hidden_workloads_pass` | H-A* / H-B* | — | yes (DB counts for A) | yes | no |
| `final_service_available` | public pass set | — | derived | yes | no |
| `integrity_provenance_pass` | composite | — | partial | yes | no |
| `source_provenance` | active_root ≠ None | — | weak | **no** | no |
| `candidate_provenance` | candidate_root ≠ None | — | weak | **no** | no |
| `deployment_provenance` | roots + DB row | — | yes | via integrity | no |
| `transcript_integrity` | no prohibited tools | — | computed | **NO (ignored by ladder)** | no |
| `bounded_resources` | transcript bytes/actions | — | computed | **NO (ignored by ladder)** | no |
| `state_root_integrity` | auth trio only | — | partial | via integrity | no |
| `no_direct_privileged_state_access` | **hardcoded True** | — | **no** | **no** | no |

Duplication: `state_tampering` appears twice in `PREDICATE_CATEGORIES`.

## Reward-ablation matrix

Live strict grades (profile 0 unless noted):

| Ablation | Score | Notes |
|---|---|---|
| Valid `effect_exists` repair | **1.0** | Baseline |
| No diagnostic tools | **0.10** | Ladder works |
| No `recovery.restore` | **0.0** | Auth recovery fails |
| No candidate edits | **0.25** | |
| Default unedited flow | **0.70** | Public pass; shared/member fail |
| Disable-effects (`s5` returns `"disabled"`) | **0.70** | **P1–P3 and H-S1 still “pass”**; terminates publicly |
| Transcript + `system.leak_probe` step (Verifier API) | **1.0** with `transcript_integrity=false` | Ladder ignores it |
| Huge forged byte counts | **1.0** with `bounded_resources=false` | Ladder ignores it |
| Empty transcript + good files | **0.0** | |
| Fabricated diagnostic names + good files | **1.0** | Transcript forgery |
| `protocol_abuse=True` (unit) | **0.0** | Dead in live grader |
| `integrity_true` but transcript/bounded/privileged false (unit) | **1.0** | Confirms holes |

Reward is deterministic and in `[0,1]` for exercised paths; monotonic along the documented plateaus; does not increase after disable-effects tampering beyond 0.70; does not trust agent-authored success flags inside `calculate_reward`.

## Valid repair matrix

| Strategy | Member A | Member B | Notes |
|---|---|---|---|
| `effect_exists(event_id)` (`IDEMPOTENT_FLOW`) | **1.0** | **1.0** | Only working gold |
| Intent/outbox via `intent_create` / `intent_complete` | **0.25 / errors** | **0.25 / errors** | Schema mismatch: code inserts `event_id,command_key,created_tick,effect_id`; table has `source_event_id,occurrence_id,state` only |
| `mark_event` alternate | **errors** | — | Code uses column `label`; table has `mark_state` |
| Structural second family | **NOT VERIFIED** | **NOT VERIFIED** | Claim of ≥2 accepted families **not met** |

`effect_exists` is event-level dedup. No hidden workload requires two legitimate distinct effects for one event, so this over-repair is **untested**.

## Wrong-control matrix

| Control | executed | exploit_path_reached | Score | Failed load-bearing preds / notes |
|---|---|---|---|---|
| Default / original flow | true | true | 0.70 | shared/member hidden |
| Retry inflation + default flow | true | true | 0.70 | member false |
| Disable-all-effects | true | true | 0.70 | member/shared; **public still pass** |
| No-op status-only | true | true | 0.0 | not terminated |
| Partial mid-policy stop | true | true | 0.25 | |
| Valid idempotent | true | true | 1.0 | |
| Direct fixture effects DELETE | true | true | 1.0 | undone by S0 — not a cheat success |
| Forged metadata session_id | true | true | 1.0 | not rejected |
| Many claimed controls (canned receipt, timeout, hardcode hidden IDs, stale public credit, snapshot forgery, delete-state, bypass-delivery, member-label leak, broad command dedup as dedicated control) | — | — | — | **NOT EXECUTED** in repo suite / this audit battery incompletely covered |

Controls suite has only four tests. Several AGENTS.md-required wrong controls lack executed exploit-path receipts.

## Hidden-workload coverage matrix

| Promised scenario | Workload | Status |
|---|---|---|
| Commit-before-ack / lost progress (A) | H-A1 `s5.exit` | **VERIFIED** (DB effect count) |
| Distinct occurrences same business key (A) | H-A2 | **VERIFIED** |
| Distinct legitimate effects per event (A) | — | **NOT IMPLEMENTED** |
| Stable logical effect identity (A) | — | **NOT VERIFIED** (intent API broken) |
| Registration response loss (B) | H-B1 `s2.exit` | **VERIFIED** |
| Same-command / same occurrence retry (B) | H-B2 | **VERIFIED** |
| Conflicting payload reuse (B) | — | **NOT IMPLEMENTED** |
| Shared transient retry | H-TRANS | **PARTIALLY VERIFIED** — hardcodes `outcome="pass"` |
| Shared recovery / no loss-excess | H-S1 | **WEAK** — counts successful deliver calls, not DB effects (disable-effects fools it) |
| Shared same-occurrence ×3 | H-S2 | **VERIFIED** (journal cardinality) |
| Public P1/P2/P3 | P1–P3 | **WEAK** — same call-success counting |
| Concurrent/interleaved redelivery | — | **NOT VERIFIED** |
| Fresh-process candidate execution | verifier in-process import of active workspace | **PARTIALLY VERIFIED** (not OS process isolation) |

## Cheat exploit matrix

| Attack | Reached intended boundary? | Outcome |
|---|---|---|
| Import `strict_verifier` from builder Python | yes | Module importable (builder profile; must be absent from evaluated mount) |
| Import hidden workloads registry | yes | Importable |
| Path traversal `workspace.read/edit` | yes | Rejected: path outside workspace |
| `runtime.run(H-A1)` | yes | Rejected unknown / gated |
| Fixture path in agent-visible JSON | yes | Not observed |
| Stale capability after restore | setup incomplete | No handle from public inspect |
| Unrestricted shell / Python via tools | yes | Unknown tool rejected |
| Transcript forgery at Verifier API | yes | **score 1.0** |
| Resource-limit transcript forgery | yes | **score 1.0** |
| Parent/absolute path | yes | Rejected |
| Symlink/junction escape | — | **NOT VERIFIED** on Windows in this audit |
| Docker socket / host root in evaluated image | — | **NOT VERIFIED** (no Docker) |

## Long-horizon measurements

Reference pair-blind policy (`training_ground.policies.valid_repair_policy`):

| Metric | Value |
|---|---|
| Policy length | **14** |
| Executed until terminate | **13** (terminates on `recovery.resume`; final `release.status` not needed) |
| Distinct tools used | **9** |
| `telemetry.trace` | **absent** |
| `release.rollback` | **absent** |
| Non-discriminating + discriminating cutpoint experiments | **absent** |
| Final score A/B | 1.0 / 1.0 |

Required narrative trajectory (status, logs, trace, state, both experiments, pause, rollback, restore, candidate read/edit, deploy, P1–P3, resume, final status) is **not** realized by the shipped reference policy.

Pair-informed shortest estimate: ~10 actions (skip diagnostics) still needs public canary path for resume.

**Pair-blind ≥15 meaningful actions: CONTRADICTED.**

## Gymnasium results

| Check | Result |
|---|---|
| `gymnasium.utils.env_checker.check_env` | **FAIL** — reset observation not in `observation_space` (`status_json` Text space) |
| Scripted gym reward vs core grade | Both 1.0 on valid policy |
| Independent strict logic in gym wrapper | No — delegates to core |
| `reset(seed=)` reshuffle | No (core ignores) |

Gymnasium compatibility is a thin Dict wrapper, **not** checker-clean.

## APEX-SWE results

Pinned upstream inspected at `7cfa580`. Supported extension point: `--tasks-dir` task folders with `task.yaml`, `docker-compose.yaml` (`client` service), and a `.sh` verifier.

| Claim | Status |
|---|---|
| Internal scripted smoke | **REAL** (`smoke_apex_scripted.py`) — **does not use apex-swe code** |
| Task-schema static compatibility | **PARTIAL** (`validate_apex_task_dir`) |
| Actual local APEX harness / `apx run` | **NOT VERIFIED** |
| Docker via APEX compose lifecycle | **NOT VERIFIED** |
| Twelve tools under APEX native terminal/file tools | **NOT VERIFIED** / **FALSE** for real `apx` agents |
| `ScriptedRecoveryPolicy` success | Public path only; **no flow.py repair**; smoke PASSED anyway |
| `verify_final_environment` includes APEX | **No** |
| Receipt APEX fields | **Absent** |

APEX integration in this repo is **compatibility packaging + side-car smoke**, not a demonstrated harness run.

## Docker / package results

| Check | Result |
|---|---|
| Docker client | Present (29.5.2) |
| Docker daemon | **Unavailable** (`dockerDesktopLinuxEngine` pipe missing) |
| Docker smoke / mount inspection | **NOT VERIFIED** |
| Dockerfile text review | Evaluated image would `pip install -e ".[adapters]"` from repo context — **risk** of shipping privileged packages unless build context is carefully minimized; **not proven** without a live container |

## Determinism results

| Artifact | Same seed ×3 | Notes |
|---|---|---|
| Instance IDs | equal | |
| Public manifests | equal | |
| Predicate maps | equal | |
| Semantic roots (`active_root`, replayed roots, etc.) | equal | |
| Scores A/B | 1.0 / 1.0 | |
| Absolute temp paths | ephemeral | Not in grade roots |
| Final receipts | timestamp differs; semantic verification equal | |

Nondeterminism observed only in ephemeral paths and receipt timestamps.

## Documentation and receipt accuracy

| Claim | Reality |
|---|---|
| “All 84 targeted tests … pass” | **True** (reproduced) |
| Final integrated build complete | **Overstated** vs contract gaps |
| `docs/VERIFIER.md` ladder / `StrictVerifier` / `env.verify()` | **Stale / wrong** vs `Verifier.grade` + `reward.py` |
| `AGENTS.md` “Milestone 2 closed / not allowed yet: later milestones” | **Stale** vs README final-build claim |
| Transcript integrity required for 1.0 | **False** in code |
| APEX / Gymnasium readiness | **Overstated** |
| Source-bound deterministic receipt | **Partially false** at receipt tip |
| Container isolation | Documented as NOT VERIFIED historically; still NOT VERIFIED |
| Final receipt completeness | **Inadequate** for hiring-trial evidence |

## Critical findings

1. **Final source binding is unsafe.** `verify_final_environment.py` binds `HEAD` and omits `validate_source_commit`. Regen at receipt tip labels the receipt commit as the tested source.
2. **Reward ladder ignores `transcript_integrity` and `bounded_resources`.** Live Verifier API grades scored **1.0** with both false.
3. **Transcript is name-trusting and unbound.** Fabricated diagnostic tool names + good candidate files → **1.0**.
4. **Public / H-S1 workload outcomes can be fooled by fake `s5` returns** (disable-effects still passes P1–P3 and H-S1; episode can terminate).
5. **`no_direct_privileged_state_access` hardcoded `True`; `protocol_abuse` never set.**
6. **Second valid repair family is broken.** Intent/mark helpers disagree with SQLite schema; only `effect_exists` reaches 1.0.
7. **Pair-blind ≥15-action horizon is false.** Reference policy is 14 actions; executes 13; lacks trace, rollback, and discriminating experiments.
8. **Final receipt is not sufficient trial evidence.** Missing suite breakdown, workload counts, controls/cheats/exploit flags, ablations, horizon, APEX/Docker, limitations.
9. **APEX “PASSED” smoke does not demonstrate strict success or upstream harness use.**

## Major findings

1. Gymnasium `check_env` fails; seed reset does not reshuffle instances.
2. Controls/soundness/final_core test suites are far thinner than the claimed adversarial battery.
3. Profile is deterministically inferable from public `SPLIT_OFFSETS` + seed.
4. Hidden coverage gaps: multi-effect-per-event, conflicting payload (B), concurrent redelivery; H-TRANS hardcodes pass.
5. `state_root_integrity` does not compare expected semantic roots.
6. Reset cannot reuse the same work_dir after close (fixture mkdir).
7. Documentation drift (`VERIFIER.md`, `AGENTS.md` stage text).
8. Builder HMAC keys committed in source (expected for builder; fatal if evaluated mount includes `src/`).
9. Docker isolation **NOT VERIFIED**.

## Minor findings

1. `state_tampering` duplicated in `PREDICATE_CATEGORIES`.
2. `arguments: []` coerced to `{}` via falsy `or {}`.
3. Extra action fields accepted.
4. APEX result filenames/schemas diverge from upstream `TaskExecution` / `test_results.json`.
5. README layout tree omits final packages that README body claims.

## Claims still NOT VERIFIED

- Real `apx run` / APEX harness E2E  
- Docker evaluated-container contents and mounts  
- Symlink/junction escapes  
- Full wrong-control and cheat matrices with exploit-path flags  
- Two structurally different gold repairs  
- ≥15 meaningful pair-blind causal actions  
- Conflicting-payload and multi-effect-per-event hidden coverage  
- Production-grade isolation / tamper resistance  

## Exact required fixes

1. Wire `validate_source_commit` into `verify_final_environment.py` with `--source-commit`; fail closed on dirty/disallowed trees; never bind receipt-only HEAD.
2. Put `transcript_integrity`, `bounded_resources`, and a real `protocol_abuse` / privileged-access check into the 1.0 gate (or honestly remove them from the contract).
3. Bind transcripts to session digests; reject fabricated name-only investigation.
4. Make public/shared workloads assert durable journal/effect rows, not deliver-call success; stop hardcoding H-TRANS pass.
5. Align intent/mark schema with RuntimeStore APIs; demonstrate a second gold repair family end-to-end for A and B.
6. Extend pair-blind reference policy to ≥15 meaningful actions including trace, rollback, and both diagnostic experiments — or narrow the horizon claim.
7. Add hidden workloads for multi-effect-per-event and conflicting payload; reject unsafe `effect_exists` over-repair if multi-effect is in-contract.
8. Expand controls/cheats with `executed` / `exploit_path_reached` / failed predicates; persist them in the receipt.
9. Fix Gymnasium observation_space / checker failures; make `reset(seed=)` either reshape the episode or document non-compliance.
10. Either run and receipt a real upstream APEX path without overclaiming, or downgrade docs to “task-pack compatibility + side-car smoke.”
11. When Docker is available, execute container probes and record mounts/contents; until then keep **NOT VERIFIED**.
12. Rewrite `evidence/final-environment.json` schema to include the matrices listed in §19; regenerate after source binding is fixed.
13. Repair `docs/VERIFIER.md` and stage text in `AGENTS.md` to match executable reality.

## Final verdict

**FAIL**

| Question | Answer |
|---|---|
| Is strict reward sound enough for evaluation? | **No** — member-hidden bar still bites for 1.0, but ignored predicates, unbound transcripts, and fooled public/H-S1 outcomes make the grader not contract-sound. |
| Is the environment usable as a training ground? | **Partially** — core rollouts work; reset/seed/Gymnasium/APEX issues and misleading smokes reduce fitness. |
| Is the pair-blind long-horizon claim supported? | **No** |
| Is Gymnasium compatibility real? | **Partial wrapper only; `check_env` fails** |
| Is APEX-SWE compatibility real? | **Task-pack shaped; harness E2E NOT VERIFIED; smoke ≠ strict** |
| Is the final receipt trustworthy? | **No** as hiring-trial evidence (thin + source-binding hazard) |
| May the branch be merged to `main`? | **No** |
| Is the repository ready for submission? | **No** |

Do not merge to `main` on the basis of 84 green tests or the current `evidence/final-environment.json`.

## Final cleanliness

Post-audit status commands to be re-run after writing this report; only this file may differ in the trial repo; APEX-SWE must remain unchanged.
