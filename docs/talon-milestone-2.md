# Talon Milestone 2: conservative offline RL and replay

Milestone 2 is a simulation-only research implementation. It does not claim that
discrete CQL is production-safe, operationally validated, or suitable for a
physical response system. The highest Talon action remains an abstract
recommendation. The deterministic policy gate and strict verifier remain the
only authorities for action acceptance and strict success, and a human approval
is still required and consumed exactly once where the policy profile requires it.

## Offline learning boundary

`talon.discrete-cql/1.0` trains only from a verified Milestone 1 private training
dataset. The host recomputes that source digest before deriving
`talon.private-offline-rl-dataset/1.0`. No online environment call, exploration,
rollout collection, replay-buffer mutation, or evaluation feedback occurs in the
optimizer.

Each transition binds:

- opaque episode ID and timestep;
- current and next bounded public observation histories;
- the private behavior action;
- operational reward and a separate safety cost;
- termination and truncation flags;
- current and next public action masks.

The canonical digest is SHA-256 over the schema version, complete manifest and
ordered transition list, excluding only the stored `dataset_digest` field. The
manifest covers the verified source digest, generator and schema versions,
feature and action ordering, context length, transition count, instance domain,
seed domain and train-fitted normalization statistics. Every load strictly parses
the schema, recomputes the canonical digest and compares it before encoding,
normalization, training or checkpoint creation.

Private datasets, behavior actions, safety costs, verifier records and privileged
replays live only below the Talon private artifact root. They are not served by
general API routes, SSE, static assets or public exports.

## CQL objective and action selection

The GRU encoder feeds independent operational-reward and safety-cost Q heads.
Training uses target networks, masked temporal-difference targets, a discrete CQL
penalty on public-valid actions and a conservative cost floor for public-invalid
actions. Operational reward never compensates for safety cost.

**TD backup is public-mask-aware, not safety-threshold-aware.** Bootstrapped next
actions are the masked max over the public action mask only (`masked_max_q`).
Safety-threshold filtering is applied at runtime action selection
(`masked_argmax`), after which the real policy gate remains the only authority
that can accept or reject the recommendation (and consume a scoped human
approval). The gate and verifier are authoritative after selection; Q values
cannot override them.

Layered contract:

1. Reward backup action selection — public mask only (`masked_max_q`).
2. Safety TD target — uses that mask-greedy next action's safety Q.
3. Runtime safety threshold filtering — `masked_argmax` at selection time.
4. Policy gate enforcement — may still reject or consume a scoped approval.

Defaults are context 20, hidden size 256, two layers, dropout 0.1, gamma 0.99,
CQL alpha 1.0, safety threshold 0.05, learning rate 3e-4, batch size 128, 50
epochs, target update every 500 optimizer steps, gradient clipping 1.0 and seed
zero. Configuration and the verified offline-dataset digest are checkpoint-bound.

Frozen action selection is ordered:

1. apply the public, side-effect-free policy mask;
2. reject candidates whose predicted safety cost exceeds the threshold;
3. choose the remaining action with maximum operational Q;
4. deterministically choose `ABSTAIN_INSUFFICIENT_EVIDENCE` if none remain;
5. submit the raw recommendation to the real policy gate, which may still reject
   it or consume a scoped human approval.

Mask construction never consumes approval. Public approval availability can make
the abstract mitigation recommendation mask-eligible, but only the real gate can
verify and atomically consume it. Q values cannot override the gate or verifier.

Python, NumPy and Torch process-global random state is not used for shuffling.
Training jobs run in spawned processes; in-process tests use a lock plus Torch
`fork_rng` and a per-run `torch.Generator`. Identical seeds are reproducible in
sequential and concurrent tests, while different seeds produce different weights.

## Checkpoint integrity (`talon.offline-rl-checkpoint/2.0`)

Completed discrete CQL runs publish an immutable checkpoint that serialises both
the online and target network `state_dict`s (`online_state_dict` /
`target_state_dict`), training configuration, verified offline/source digests,
feature/action schema bindings, environment and verifier compatibility versions,
and a training-updates count when available.

### Provenance contract (`TrustedCheckpointBinding`)

Product evaluation, orchestration and worker paths prefer a structured
`TrustedCheckpointBinding` over a bare digest string. The binding carries:

- `checkpoint_id` / `training_run_id`;
- `offline_dataset_digest` / `source_dataset_digest` (required for offline CQL
  product evaluation; copied from the completed training record into evaluation
  configuration and enforced at `load_offline_checkpoint` time);
- `artifact_identity` — a logical path under the private root
  (`{run_id}/checkpoint.pt`), never a raw absolute path as the sole trust anchor;
- `trusted_digest` — SHA-256 of the full file bytes after atomic publication;
- `binding_source` — one of `immutable_db_record`, `verified_manifest`, or
  `cli_operator_supplied`.

The trusted digest must come from an immutable completed-run record (API/DB) or
an equivalent out-of-band source that originated from that record. Digests
embedded inside the checkpoint payload are never the trust anchor. A forged
record that claims another dataset's digests while pointing at a different
artifact fails closed on digest-binding mismatch before inference.

CLI load and evaluate paths still accept `--trusted-checkpoint-digest` (alias
`--checkpoint-digest`). Optional `--offline-dataset-digest` and
`--source-dataset-digest` may be supplied together when the operator has a
verified binding; product DB paths always bind both digests. Help text states
the checkpoint digest must originate from an immutable completed-run record; the
CLI prints a short stderr note that a CLI-supplied digest is operator-supplied
provenance, not a DB binding.

Behaviour-cloning (`talon.checkpoint/2.0`) checkpoints also bind
`environment_version` and `verifier_version` on save. Product evaluation requires
current compatibility: legacy payloads missing those fields are rejected as an
unsupported checkpoint format, and mismatched versions fail closed.

### Artifact identity enforcement

Completed training records bind `artifact_identity` relative to
`TALON_DATA_DIR/private/`. On product evaluation/load:

1. resolve the identity under the approved private root;
2. reject `..` traversal and practical symlink/junction escape (including on
   Windows after `Path.resolve()`);
3. reject any path outside the private root;
4. reject path-record mismatch (resolved parent must be the bound run directory);
5. require a trusted digest match on file bytes.

Path substitution (pointing `paths["checkpoint"]` at another file), copying a
checkpoint under a different run's directory while keeping another run's digest,
and free-form absolute paths as the sole trust anchor are rejected.

### Interrupted artifact cleanup and restart reconciliation

When `mark_active_interrupted` terminalises active runs on API restart it removes
uncommitted `*.partial` files and any published `checkpoint.pt` for that run that
has **no** completed immutable checkpoint record. Completed runs' checkpoints are
never deleted.

`reconcile_orphan_checkpoints` (invoked from restart interruption) applies:

| State | Action |
| --- | --- |
| A. completed + valid file | keep; mark available |
| B. completed + missing/invalid | mark unavailable via health table; do not silently accept |
| C. non-completed + checkpoint file | remove/quarantine |
| D. checkpoint file with no DB record under `private/` | quarantine/remove |
| E. `*.partial` | remove |

API, CLI product paths and evaluation refuse unavailable or orphaned interrupted
checkpoints.

`load_offline_checkpoint` is fail-closed: `expected_digest` is required and must
be a well-formed `sha256:` hex digest; file bytes are compared with
`hmac.compare_digest` before weights are deserialised; optional expected bindings
(offline/source digests, actions, gamma, alpha, safety threshold, schemas) are
checked when supplied. Legacy `talon.offline-rl-checkpoint/1.0` payloads are
rejected without fabricating a target network.

Target weights are stored so a verifier can confirm the published backup network
matches the training run. **Resume training is not supported**: optimizer state is
not serialised, and reloading a checkpoint for continued optimisation is out of
scope unless a future format fully implements optimizer state and a documented
resume contract.

## Evaluation and process isolation

Evaluation uses disjoint validation/evaluation generator partitions, rejects an
instance digest present in the checkpoint training domain, loads immutable
weights with no optimizer, and records zero evaluation optimizer steps.
Policy inference runs under `python -I` in a temporary weight-only directory. It
receives normalized features derived solely from the public observation history
and a public action mask. The worker cannot import simulator, hidden-scenario,
training or verifier modules and loses filesystem access after startup.

The public `evaluate_offline_checkpoint` / `evaluate_checkpoint` entry points do
**not** accept an injectable `policy_client`. Production always constructs
`IsolatedCQLPolicyClient` / `IsolatedPolicyClient` from the verified checkpoint
binding. Worker payloads cannot inject a client. Tests that need injection use
the clearly named helpers `evaluate_offline_checkpoint_for_tests` /
`evaluate_checkpoint_for_tests`. A foreign-weight client cannot be paired with
another verified checkpoint through the production path.

Dataset generation, training orchestration and strict grading remain privileged
host processes. This is role and process isolation; privileged source modules
remain present in the complete repository but are not model-visible at inference.

Evaluation metrics include strict success, operational score, safety violations,
false escalation, missed threat, abstention, gate intervention, invalid action,
evidence efficiency, approval correctness, action count, calibration, held-out
expert agreement and worst-case score. Strict success is copied from the verifier,
never calculated by the dashboard or learned policy.

## Human-readable replay

Completed CQL episodes produce an immutable
`talon.public-episode-replay/1.0`. The replay orders simulated clock, public track
state, evidence lifecycle, raw model action, bounded Q/safety summaries, model
confidence, abstention, gate reasons, effective action, approval lifecycle and
termination. It intentionally does not collect or retain chain of thought.

Public replay routes use an explicit allowlist and expose only policy-visible
state plus already-public gate/verifier outcomes. Hidden family, paired identity,
true intent, expert labels, safety-cost targets and verifier predicates remain in
the separate post-termination privileged replay. Public replay mutation or
reordering invalidates its digest.

The dashboard supports play/pause, previous/next, a scrubber, speed, keyboard
navigation, auto-scroll, filtering, track selection, fullscreen, reduced motion,
accessible tables and safe JSON download. Q-value displays are diagnostics, not
safety certification.

## API surface

The existing local Talon prefix remains `/api/drone`. Milestone 2 adds:

- `POST/GET /api/drone/offline-rl/training-runs`;
- `GET /api/drone/offline-rl/training-runs/{id}` and its metadata-only
  `/checkpoint` endpoint;
- `POST/GET /api/drone/offline-rl/training-runs/{id}/cancel` and `GET .../events`;
- `POST/GET /api/drone/offline-rl/evaluations` and `GET .../{id}/events`;
- `GET /api/drone/episodes/{episode_id}/replay`;
- `GET /api/drone/episodes/{episode_id}/replay/events`;
- `GET /api/drone/episodes/{episode_id}/replay/export.json`;
- `POST/GET /api/drone/comparisons` for domain-compatible immutable
  comparison records.

Mutations remain loopback- and origin-restricted, idempotency-bound, cancellable
and timeout-bounded. Completed records remain digest-bound and immutable. Retention
deletion follows dependency protection and quarantine recovery from Milestone 1.

## Known limitations

The initial CQL encoder is GRU-based; a transformer encoder is not implemented.
The verified safe behavior dataset has sparse positive safety costs, so invalid
public actions use a conservative cost margin rather than claiming learned
coverage of every unsafe behavior. Paired consistency is the conservative share
of deterministic authorised-inspection/perimeter-probing pairs for which both
members receive strict success; it does not expose pair identity in episode
records. These limitations are visible and should be considered in independent
review before any evidence generation.
