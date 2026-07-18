# Talon Milestone 1 remediation plan

Status: implemented but intentionally uncommitted, pending a second independent
adversarial review. This document describes the implementation; it is not an
evidence receipt or a certification.

## Safety boundary

Talon is a deterministic, simulation-only decision-support system. Its thirteen
actions are abstract recommendations. The highest recommendation requires a
one-time simulated human approval, and every policy-gate result fixes
`external_effect=false`. No hardware, radio, interception, aircraft-disabling,
physical engagement, mechanism selection, or external-response execution is in
scope.

## Implemented remediation

1. Public schemas contain only opaque episode/track identifiers and observed
   evidence. Privileged family, partition, instance, truth, label, and predicate
   data stay in verifier-owned private artifacts. A recursive post-serialization
   scanner checks both keys and values.
2. Train, validation, and evaluation use domain-separated deterministic generation,
   different transition parameters, disjoint canonical instance digests, and
   training-only normalization. Evaluation rejects checkpoint overlap.
3. Evidence is causal: requests have deterministic latency, availability,
   deduplication, failure, freshness, expiry, and request-cost behavior. Command-link
   state is available only through `REQUEST_COMMAND_LINK_VERIFICATION`; unrelated
   sensor confirmation and passive waiting cannot reveal it.
4. Fifteen privileged scenario profiles have unique behavioral signatures and
   exercise identity, evidence, authority, track, command-link, and safe-disposition
   differences. Public catalogue entries describe only generic capabilities.
5. Evaluated step reward is always zero. Detailed utility and predicates are
   calculated only after termination by the privileged verifier.
6. Approval is HMAC-protected, unpredictable, short-lived, state/episode/track/
   action/profile-bound, revoked on relevant authority change, and atomically
   single-use.
7. Learned policies run in a separate `python -I` process from a weight-only public
   bundle. Repository source paths, Talon/verifier environment metadata, filesystem
   reads, package listing, and privileged imports are denied and dynamically probed.
8. Strict verification is semantic rather than exact-plan matching. Two different
   public-only safe policies pass; deterministic negative controls fail for semantic
   reasons. Non-compensable safety failures force strict failure.
9. Decision Transformer return-to-go uses the private offline trajectory reward
   consistently in training and inference. Padding is masked. The unsupported
   `policy_risk` head and claim were removed.
10. Feature encoding distinguishes zero, missing, unknown, and not-applicable values;
    validates finite ranges; and encodes related-track aggregates deterministically.
11. Training uses a per-run Torch generator, restores temporary model-initialization
    RNG state under an in-process lock, does not use Python or NumPy global RNGs,
    and runs production jobs in independent spawned processes. Cancellation and
    timeout terminate the worker before finalization.
12. Checkpoints are validated and digest-bound before atomic publication, immutable
    after completion, and removed after non-completion.
13. Create operations support payload-bound idempotency. Persistence tracks artifact
    dependencies and uses restart-safe deletion plans and quarantine.
14. Talon initialization is lazy. A Talon database or migration failure yields a
    bounded Talon 503 while original Frontier routes remain available.
15. Public records and evaluation exports use explicit allowlists. Private datasets,
    training manifests, and verifier records remain outside public routes and SQLite.
16. The separate dashboard consumes only safe public schemas and labels the system
    simulation-only, decision-support-only, and human-approval-bound.
17. Private datasets use one canonical serialization and SHA-256 digest. Every load
    strictly parses and recomputes the digest before normalization, training,
    evaluation, inspection, or checkpoint creation.

## Verification levels

Dynamic verification covers simulator behavior, partitions, approvals, policy gate,
semantic controls, models, checkpoints, process isolation, real worker lifecycle,
SQLite/SSE/API wiring, and real Playwright Talon journeys. Dashboard unit tests use
mocked API responses and are not counted as end-to-end proof. Typecheck, lint,
production build, dependency audit, lock consistency, diff checks, and physical
boundary scans are static or build-time checks.

The verifier supports a dirty-tree development mode:

```powershell
uv run --extra talon --extra test python scripts/verify_talon_milestone_1.py --check-only
```

Without `--check-only`, it refuses a dirty tree and may write a source-bound receipt.
Do not generate that receipt until a clean source commit has passed independent
review.

## Deferred

Online reinforcement learning, raw or live sensors, real-world authority workflows,
multi-tenant isolation, external response systems, operational deployment, and a
free-form explanation model remain out of scope and unverified.
