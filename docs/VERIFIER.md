# Verifier

## `strict_verifier`

`src/strict_verifier/` is the deterministic ground-truth grader. It evaluates an
agent repair against canonical state, authenticated episode transcripts, durable
state effects, deployment provenance, and the paired hidden workload matrix.

### Modules

- `verifier.py` — `StrictVerifier` and the main `verify`/`grade` entrypoint.
- `predicates.py` — verifier predicate names including workload, provenance,
  transcript, resource, and privileged-access gates.
- `workloads.py` — `hidden_matrix_for_profile`, `public_workload_ids`, and
  public/shared/member workload registries.
- `reward.py` — `calculate_reward` with the monotonic 0.0 to 1.0 ladder.
- `integrity.py` — `IntegrityTree` and `MerkleTree` for canonical roots.
- `reconstruct.py` — `reconstruct_state_root` for state verification.
- `result.py` — `VerificationResult` dataclass.

### Reward ladder

| Step | Condition | Score |
|---|---|---|
| diagnostic evidence | `telemetry.logs` or `state.inspect` used | 0.1 |
| initial investigation | both telemetry and state inspect | 0.15 |
| public workloads pass | P1/P2/P3 receipts pass | 0.55 |
| shared hidden pass | H-TRANS, H-S1, H-S2 pass | 0.70 |
| member hidden pass | H-A1/H-A2 or H-B1/H-B2 pass | 0.85 |
| full evidence | all mandatory workload, provenance, transcript, resource, and privileged-access gates | 1.0 |

`transcript_integrity`, `bounded_resources`, `no_direct_privileged_state_access`,
`no_verifier_modification`, and `no_hidden_workload_modification` are mandatory:
if any are false, full credit is rejected.

### Accepted gold families

The current pair-blind gold repairs are:

- logical effect identity via `effect_by_key`;
- intent/outbox repair via `intent_create`, `get_intent`, and `intent_complete`.

Both are expected to score `1.0` on profiles `0` and `1`.

### Usage

```python
from training_ground import load_environment
from strict_verifier import Verifier

env = load_environment("eval", 0, options={"max_steps": 64})
env.reset()
# run agent actions
result = env.grade()
print(result["score"], result["verdict"])
```
