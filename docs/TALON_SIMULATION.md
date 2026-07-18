# Talon simulation-only decision training

## Boundary and threat model

Talon accepts synthetic structured track observations and returns an abstract
recommendation. It cannot operate a vehicle, transmit radio energy, select a
physical technique, contact an external authority, or execute a response. The
deterministic policy gate can accept or replace a recommendation only in the
simulation transcript. Its output always has `external_effect=false`.

The highest action, `RECOMMEND_AUTHORISED_MITIGATION`, contains no technique or
mechanism. It is accepted only after fresh required evidence, sufficient current
authority, a matching active track, and a privileged simulated-human approval.

```text
public observation -> isolated learned policy -> abstract recommendation
                   -> deterministic gate -> simulated transcript only
privileged truth ---------------------------------> strict verifier after termination
```

The local process boundary is a research/development control, not a production
sandbox or multi-tenant security claim. Evaluated policy inference runs in the
isolated `python -I` worker. Dataset generation, training orchestration, and strict
grading run in a privileged host process that can access private simulator and
verifier modules. This is role/process isolation; hidden modules remain present in
the complete repository but are intentionally absent from model-visible inputs.

## Public and privileged data

Public observations use `talon.observation/2.0`. They include observable track
kinematics, confidence, related public tracks, current authority, Remote ID status,
command-link status, evidence provenance/freshness, pending requests, operator and
proximity context, and a scoped approval summary. Extra or non-finite values fail
validation.

Episode and track IDs are keyed opaque values. They contain no readable family,
member, seed, partition, expected outcome, or label. Reset/step info, policy input,
SSE, SQLite, dashboard responses, and reviewer exports never contain privileged
family names, instance digests, expert actions, truth, or verifier predicate names.

The privileged simulator retains the concrete profile, transition graph, expected
safe disposition, evidence dependencies, partition, seed, instance digest, and full
predicate record. Private training trajectories additionally contain expert actions.
Those artifacts are stored under `TALON_DATA_DIR/private/<record-id>` and are not
mounted in the policy runtime or exposed by general routes, SSE, static dashboard
assets, demo bundles, or reviewer exports. Private datasets contain expert labels
and are privileged artifacts, never public evaluation material.

The leak scanner recursively examines keys and values for known and derived family
identifiers, paired aliases, privileged field patterns, predicate names, private
paths, credentials, tokens, raw reasoning, and operator personal data. Public
serialization fails closed when a finding exists.

## Causal scenarios and partitions

There are fifteen privileged behavior profiles, represented publicly by five generic
capability groups. Concrete profile names and paired membership are deliberately not
part of the public catalogue or active-episode response.

Every profile has a canonical private signature covering hidden transition graph,
evidence dependency, track evolution, authority changes, safe terminal disposition,
sensor behavior, and source availability. Tests reject duplicate signatures.
Profiles collectively exercise benign, authorized, emergency, false-positive,
credible, ambiguous, out-of-distribution, multiple-track, stale-track, command-link,
Remote ID, unavailable-source, nearby-people, and authority-change behavior.

Evidence actions create pending requests. `REQUEST_COMMAND_LINK_VERIFICATION` is
the sole instrument that can produce command-link evidence; sensor confirmation and
passive waiting cannot do so. Deterministic latency, availability,
failure, staleness, freshness, deduplication, request limits, and waiting cost affect
what becomes observable. Evidence never appears merely because a fixed timestep was
reached. A policy can fail by requesting the wrong source, acting before completion,
using stale evidence, exhausting requests, looping, or waiting past a private threat
deadline.

Command-link verification can complete with a public healthy, degraded, lost,
not-applicable, or unknown result, or fail safely when its source fails or is
unavailable. Its records expire through the same freshness lifecycle. A stale link
record cannot satisfy strict evidence or authorize a consequential recommendation.

Train, validation, and evaluation domains derive independent seeds under
`talon.partition-domain/2.0`. They differ in parameters and transition behavior even
when the numeric seed matches. Each instance has a private SHA-256 digest. Training
manifests bind all training instance digests and the seed-domain digest. Frozen
evaluation rejects any overlap. Only training observations fit normalization;
validation and evaluation never update weights or preprocessing.

Private dataset schema `talon.private-dataset/3.0` has one canonical JSON digest
input. It covers dataset and manifest schema versions, dataset/generator versions,
partition and seed domain, instance digests, ordered feature schema, thirteen-action
vocabulary, normalization means/scales/mask, complete ordered trajectories,
observations, expert labels, supervised targets, private rewards, and terminal
records. Only the stored `dataset_digest` value is omitted. Every loader strictly
parses, recomputes, and safely compares the digest before data can affect
preprocessing, weights, evaluation, inspection, or checkpoint metadata.

## Approval lifecycle

The privileged simulated-human authority issues an HMAC-protected record containing:

- unpredictable approval ID and nonce;
- issue and expiry times;
- episode, active track, requested action, policy profile and profile-version binding;
- approver scope and current state revision;
- status and atomic consumption state.

Plain enums are never proof of approval. Consumption fails deterministically for a
missing, malformed, modified, expired, replayed, wrong-episode, wrong-track,
wrong-action, wrong-profile, wrong-version, stale-state, or revoked record. Authority
revocation invalidates active approvals. Only a bounded public status and scope
digest appear in an observation.

## Policy-process isolation

The privileged parent validates a digest-bound checkpoint, creates a new public weight-only
bundle with no training-instance metadata, copies a standalone worker into a fresh
temporary directory, sanitizes its environment, and starts `python -I worker.py`.
The JSON-line protocol accepts only reset, recommend, probe, and close messages with
a 65,536-byte bound and response timeout.

After loading weights, the worker denies ordinary file reads and directory listing.
Repository source paths are removed from `sys.path`; privileged packages and metadata
are absent from arguments and environment. Exceptions crossing the boundary use
bounded category codes and do not include source paths or truth. Executable probes
verify each property.

Training is intentionally privileged, but each API/CLI job runs in a separate
spawned process. Model initialization temporarily seeds Torch inside a restored RNG
scope, batch shuffling uses a per-run `torch.Generator`, and the training path does
not mutate Python or NumPy global RNG state. Direct concurrent in-process callers
are serialized around Torch's constructor RNG; production concurrent jobs do not
share a process RNG.

## Semantic verification and reward

The public step reward is always `0.0`, including gate rejection, so an adaptive
policy cannot probe hidden correctness. At termination, the privileged verifier
evaluates semantic properties such as causal evidence, current authority, approval,
identity binding, protected-flight stand-down, credible-threat timeliness, crewed
ambiguity, stale tracks, disagreement, revocation, loop bounds, and safe final
disposition.

Multiple action sequences may satisfy the same outcome. Two structurally different
safe policies are positive controls. Negative controls for over/under escalation,
missing checks, stale/wrong tracks, metadata assumptions, approval misuse, evidence
bypass, unsupported action, looping, revocation, ambiguity, and wrong disposition
must fail without assigning their own score.

Severe safety predicates are non-compensable: any such failure makes the public
strict score zero regardless of operational predicate reward. Public completion
contains high-level failure categories only; full predicate names stay privileged.

## Models and metrics

Talon provides a GRU and a causal Decision Transformer. Both predict the next
abstract action plus supervised threat, uncertainty, and missing-evidence targets.
There is no `policy_risk` output. Decision Transformer return-to-go is the canonical
undiscounted sum of private offline rewards, padded with zero under a causal mask.
Inference uses the checkpoint's documented safe terminal target; public evaluated
reward remains zero.

Reports distinguish:

- in-sample training action accuracy;
- frozen validation action accuracy on the validation partition;
- frozen held-out action accuracy on the evaluation partition;
- strict success and safety-violation rates;
- false-escalation, missed-threat, abstention, and gate-confidence calibration rates.

Training accuracy is not a generalization or safety claim. Strict success remains
verifier-authoritative.

## Persistence and lifecycle

Talon uses its own SQLite database and private artifact tree. Job workers have no
database handle. Spawned dataset/training/evaluation processes send bounded public
events to the parent. Timeout and cancellation terminate the worker before the
single immutable terminal event and remove partial outputs.

Checkpoints are written to a same-directory temporary file, flushed, fsynced,
validated, digest-checked, atomically published without replacement, and made
read-only. Idempotency keys bind operation and canonical payload. Dependency records
prevent deletion of referenced datasets or checkpoints. Deletion uses a persistent
plan and quarantine so restart recovery can roll forward or restore safely.

Talon initializes lazily. Its database corruption, path, permission, or migration
failure cannot block original Frontier routes; Talon returns a bounded 503 and may
retry initialization.

## Verified versus deferred

Python tests dynamically exercise the environment, workers, API/SSE, persistence,
approvals, models, isolation, and controls. Playwright uses the real local API,
workers, SQLite, dashboard, SSE, export, approval, and gate. Unit tests with mocked
fetch validate rendering only. Lint, typecheck, build, dependency audit, lock check,
diff check, and source safety search are static/build-time checks.

No production sandbox, real sensor, hardware, operational authority integration,
external response, deployment safety case, or online learning is verified.
