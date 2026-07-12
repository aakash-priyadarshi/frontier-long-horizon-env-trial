# Final audit regression baseline

## Outcome

The final-audit regression suite is intentionally red against the audited source at
base commit `19bf96719de231b4f142c31d2cf9033ef3c7d7d7`.

- Collected: **133**
- Passed: **21**
- Failed: **112**
- Skipped: **0**
- Collection errors: **0**
- Baseline outcome: **expected failure**

The definitive run used Python 3.12.13 and pytest 8.4.2 from the ignored repository
virtual environment. The requested plain command was exercised, and a second local
run added `--tb=no` plus a temporary JUnit file solely to capture exact node IDs:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\final_audit --collect-only -q
.\.venv\Scripts\python.exe -m pytest tests\final_audit -q
.\.venv\Scripts\python.exe -m pytest tests\final_audit -q --tb=no --junitxml=<temporary-file>
```

All mutation probes use pytest temporary directories or disposable temporary Git
repositories. The suite makes no network calls, uses no paid APIs, and does not
alter the repository working tree.

## Expected baseline failures

The following are the exact failing node IDs, compacted only where a single
parameterized test has an explicitly enumerated parameter set.

### Source binding — 10 failures

- `test_missing_source_commit_is_rejected`
- `test_receipt_tip_cannot_be_misbound_as_source`
- `test_nonexistent_commit_is_rejected`
- `test_blob_sha_is_rejected`
- `test_short_sha_is_rejected`
- `test_dirty_protected_tree_is_rejected[dirty-source]`
- `test_dirty_protected_tree_is_rejected[dirty-tests]`
- `test_dirty_protected_tree_is_rejected[dirty-scripts]`
- `test_receipt_only_tip_binds_explicit_source_parent`
- `test_permitted_receipt_difference_does_not_dirty_source`

These encode critical finding C1: the final verifier has no recognized,
fail-closed `--source-commit` interface and cannot reproducibly bind an explicitly
validated source parent while allowing only the receipt difference.

### Authenticated transcript integrity — 12 failures

- `test_fabricated_diagnostic_tool_names_cannot_score_one`
- `test_reordered_transcript_is_rejected`
- `test_deleted_step_is_rejected`
- `test_duplicated_step_is_rejected`
- `test_altered_tool_is_rejected`
- `test_altered_step_evidence_is_rejected[argument-digest]`
- `test_altered_step_evidence_is_rejected[result-digest]`
- `test_altered_step_evidence_is_rejected[request-bytes]`
- `test_altered_step_evidence_is_rejected[response-bytes]`
- `test_cross_session_transcript_is_rejected`
- `test_cross_seed_transcript_is_rejected`
- `test_cross_member_transcript_is_rejected`

These encode critical finding C3. The current verifier trusts caller-supplied tool
names and does not authenticate transcript order, cardinality, digests, byte counts,
or episode identity.

### Mandatory reward gates — 9 failures

`test_false_strict_gate_prevents_score_one` fails for each of:

- `[transcript_integrity]`
- `[bounded_resources]`
- `[source_provenance]`
- `[candidate_provenance]`
- `[deployment_provenance]`
- `[state_root_integrity]`
- `[no_direct_privileged_state_access]`
- `[verifier_integrity_pass]`
- `[workload_integrity_pass]`

These encode critical findings C2 and C5 plus major finding M5. Each ablation starts
from an otherwise all-true strict predicate set, so the failures demonstrate that
these individual predicates do not currently prevent score 1.0.

### Durable public/shared workload semantics — 36 failures

`test_public_and_shared_workloads_require_durable_semantics` fails for these exact
parameter combinations:

- `[fake-effect-id-P1]`, `[fake-effect-id-P2]`, `[fake-effect-id-P3]`,
  `[fake-effect-id-H-S1]`, `[fake-effect-id-H-S2]`,
  `[fake-effect-id-H-TRANS]`
- `[effects-disabled-P1]`, `[effects-disabled-P2]`,
  `[effects-disabled-P3]`, `[effects-disabled-H-S1]`,
  `[effects-disabled-H-S2]`, `[effects-disabled-H-TRANS]`
- `[duplicate-journal-row-P1]`, `[duplicate-journal-row-P2]`,
  `[duplicate-journal-row-P3]`, `[duplicate-journal-row-H-S1]`,
  `[duplicate-journal-row-H-TRANS]`
- `[duplicate-effect-row-P1]`, `[duplicate-effect-row-P2]`,
  `[duplicate-effect-row-P3]`, `[duplicate-effect-row-H-S1]`,
  `[duplicate-effect-row-H-S2]`, `[duplicate-effect-row-H-TRANS]`
- `[wrong-amount-P1]`, `[wrong-amount-P2]`, `[wrong-amount-P3]`,
  `[wrong-amount-H-S1]`, `[wrong-amount-H-S2]`,
  `[wrong-amount-H-TRANS]`
- `[stale-cursor-P1]`, `[stale-cursor-P2]`, `[stale-cursor-P3]`,
  `[stale-cursor-H-S1]`, `[stale-cursor-H-S2]`,
  `[stale-cursor-H-TRANS]`

The additional exact failure is
`test_transient_cannot_claim_pass_without_durable_effect`.

These encode critical finding C4 and major findings M4/M5. Public and shared hidden
receipts currently trust delivery return paths or hard-coded counts instead of
checking canonical journal/effect amounts, cardinality, cursor progress, and the
transient effect row.

### Supported repair families — 8 failures

- `test_stable_logical_effect_identity`
- `test_multiple_legitimate_effects_for_one_event`
- `test_replay_same_logical_effect_does_not_duplicate`
- `test_conflicting_payload_reuse_is_rejected`
- `test_intent_outbox_repair_family_is_accepted[0]`
- `test_intent_outbox_repair_family_is_accepted[1]`
- `test_alternate_atomic_registration_progress_family_is_accepted[0]`
- `test_alternate_atomic_registration_progress_family_is_accepted[1]`

These encode critical finding C6 and major finding M4. The intended intent/mark
schema is inconsistent with its runtime APIs, stable logical effect identity is not
supported, conflicting payload reuse is not rejected, and two structurally
different repair families do not score 1.0 for both profiles.

### Pair blindness — 1 failure

- `test_public_manifest_module_has_no_seed_to_profile_formula`

This encodes major finding M3: the public manifest module contains the direct
split/seed-to-profile derivation.

### Episode lifecycle and sanitation — 9 failures

- `test_reset_twice_reuses_same_work_directory`
- `test_reset_after_close_reuses_same_work_directory`
- `test_reset_seed_selects_the_requested_deterministic_instance`
- `test_step_after_terminated_is_rejected`
- `test_step_after_truncated_is_rejected`
- `test_arguments_list_is_rejected_not_coerced`
- `test_unknown_extra_action_fields_are_rejected`
- `test_raw_tool_response_is_sanitized_before_info`
- `test_child_process_death_is_controlled_truncation`

These encode major finding M6 and the audited episode/minor API findings: work-dir
reuse fails, reset seeds are ignored, terminal states accept further actions,
malformed/extra action fields are accepted, raw results bypass sanitation, and a
dead gateway is not converted to a controlled truncation.

### Meaningful long horizon — 5 failures

- `test_pair_blind_policy_contains_required_meaningful_action[trace-use]`
- `test_pair_blind_policy_contains_required_meaningful_action[non-discriminating-experiment]`
- `test_pair_blind_policy_contains_required_meaningful_action[discriminating-experiment]`
- `test_pair_blind_policy_contains_required_meaningful_action[rollback]`
- `test_pair_blind_policy_executes_at_least_fifteen_meaningful_actions`

These encode critical finding C7. The shipped policy executes only 13 actions and
omits trace use, rollback, and both cutpoint experiments.

### Gymnasium contract — 3 failures

- `test_gymnasium_check_env_passes`
- `test_reset_observation_belongs_to_space`
- `test_reference_action_belongs_to_space`

These encode major finding M1. The declared Text spaces reject the environment's own
JSON observation and action values, so `check_env` fails.

### APEX/Docker truthfulness and evaluated packaging — 6 failures

- `test_internal_sidecar_is_labeled_and_not_upstream`
- `test_public_only_sidecar_smoke_does_not_claim_strict_success`
- `test_docker_nonexecution_is_reported_not_verified`
- `test_upstream_harness_and_docker_have_distinct_execution_flags`
- `test_documentation_marks_unexecuted_real_paths_not_verified`
- `test_evaluated_container_recipe_excludes_privileged_builder_packages`

These encode critical finding C9 and major findings M7–M9. Internal side-car,
upstream harness, and Docker execution lack distinct provenance; skipped Docker is
not labeled NOT VERIFIED; documentation overstates unexecuted paths; and the current
container recipe copies all `src` packages plus a fixture selector into the
evaluated image definition.

### Final receipt completeness — 13 failures

- `test_receipt_has_validated_source_sha`
- `test_receipt_has_separate_suite_counts`
- `test_receipt_has_hidden_workload_counts`
- `test_receipt_has_two_gold_families`
- `test_receipt_has_executed_attack_matrix[controls]`
- `test_receipt_has_executed_attack_matrix[cheats]`
- `test_receipt_records_failed_predicates`
- `test_receipt_records_ablations`
- `test_receipt_records_horizon`
- `test_receipt_records_gymnasium_result`
- `test_receipt_records_apex_result`
- `test_receipt_records_docker_status`
- `test_receipt_records_limitations`

These encode critical finding C8 and major finding M2. The current receipt lacks the
source-validation block, per-suite/workload counts, gold/control/cheat execution
matrices, ablations, horizon evidence, adapter execution provenance, and declared
limitations required for trial evidence.

## Baseline-green checks

Twenty-one regressions already pass on the audited source. These are not false
greens: each exercises a safeguard or partial contract the audit found working.

- `test_public_and_shared_workloads_require_durable_semantics[duplicate-journal-row-H-S2]`
- `test_gym_seed_behavior_is_deterministic`
- `test_gym_and_direct_core_are_behaviorally_equivalent`
- Long-horizon structure:
  `[trace-acquisition]`, `[state-inspection]`, `[pause]`, `[restore]`, `[edit]`,
  `[deploy]`, `[public-p1]`, `[public-p2]`, `[public-p3]`, `[resume]`, and
  `[final-confirmation]`
- `test_public_workspace_is_equal_across_pair`
- `test_public_manifest_has_no_profile`
- `test_split_instance_ids_do_not_overlap`
- `test_hidden_runtime_workload_is_not_agent_callable`
- `test_same_shape_different_occurrence_is_accepted`
- `test_false_strict_gate_prevents_score_one[authenticated_recovery]`
- `test_protocol_abuse_prevents_score_one`

No test unexpectedly passed after auditing for vacuous preconditions. The green
reward tests demonstrate only that `calculate_reward` enforces those predicates
when they are explicitly supplied; the live-verifier protocol-abuse generation gap
remains covered by the red provenance/integrity tests.

## Critical and major finding coverage

| Audit finding | Executable regression coverage |
|---|---|
| C1 unsafe source binding | `test_source_binding.py` (10) |
| C2 ignored transcript/resource reward gates | `test_reward_gates.py`; transcript byte/digest mutations |
| C3 name-trusting, unbound transcript | `test_transcript_integrity.py` (12) |
| C4 fake durable workload success | `test_durable_workloads.py` (37 total, 36 red) |
| C5 dead protocol/privileged checks | protocol and privileged-access reward ablations; hidden-call boundary |
| C6 broken second repair family | `test_repair_alternatives.py` (9 total, 8 red) |
| C7 false long-horizon claim | `test_long_horizon.py` (16 total, 5 red) |
| C8 inadequate final receipt | `test_receipt_completeness.py` (13) |
| C9 misleading APEX smoke | `test_apex_truthfulness.py` (6) |
| M1 Gymnasium noncompliance | `test_gymnasium_contract.py` (5 total, 3 red) |
| M2 thin control/soundness coverage | 133-case independent final-audit suite plus receipt attack matrices |
| M3 public seed/profile inference | pair-formula regression plus public equality/manifest checks |
| M4 hidden semantic gaps | multi-effect, conflicting-payload, transient, journal/effect corruption tests |
| M5 weak semantic root integrity | state-root reward ablation plus durable amount/cardinality/cursor probes |
| M6 work-dir reset failure | reset-twice and reset-after-close regressions |
| M7 documentation drift | explicit upstream/Docker NOT VERIFIED documentation regression |
| M8 builder secrets in evaluated mount | evaluated-container package/selector exclusion regression |
| M9 Docker not verified | Docker execution/status distinction and NOT VERIFIED regression |

## Limitations

- This baseline is a source-level and local-process QA run, not a model evaluation.
- A real upstream APEX harness and Docker daemon were deliberately not invoked.
- No production fix, evidence regeneration, or isolation claim is made by this
  report.
