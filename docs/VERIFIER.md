# Verifier

## `strict_verifier`

`src/strict_verifier/` is the deterministic ground-truth grader. It evaluates an
agent repair against canonical state, behavior, and the paired hidden workload
matrix.

### Modules

- `verifier.py` — `StrictVerifier` and the main `verify`/`grade` entrypoint.
- `predicates.py` — `public_workloads_pass`, `shared_hidden_workloads_pass`,
  `member_hidden_workloads_pass`, `diagnostic_evidence`, `transcript_integrity`.
- `workloads.py` — `hidden_matrix_for_profile`, `public_workload_ids`, and
n  `expected_workload_outcomes`.
- `reward.py` — `calculate_reward` with the monotonic 0.0→1.0 ladder.
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
| full evidence | all above + `transcript_integrity` | 1.0 |

### Usage

```python
from training_ground import load_environment
from strict_verifier import StrictVerifier

env = load_environment("eval", 0)
env.reset()
# run agent actions
result = env.verify()
print(result.score, result.verdict)
```
