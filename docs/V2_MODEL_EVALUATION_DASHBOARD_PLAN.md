# V2 Model Evaluation Dashboard Plan

Status: planning only. No application scaffolding in this commit.

## Frozen submission boundary

- The original strict verifier remains the **only scoring authority**.
- Immutable tag `trial-submission-v1` stays frozen and must not be moved or rewritten.
- Branch `main` at the audited receipt commit remains the submission baseline.
- Model-evaluation and dashboard work is **version two** and is **not** part of
  `trial-submission-v1`.

## Non-goals for this plan commit

- Do not implement a model-selection UI yet.
- Do not create empty application scaffolding.
- Do not merge APEX-SWE into this repository.
- Do not compute, cache, or modify reward outside the strict verifier.

## Scoring authority

The dashboard and model runners must never compute or modify reward.

- All pass/fail and score outcomes come from the existing deterministic strict
  verifier and its canonical predicates.
- Public feedback may be displayed, but display code must not reinterpret or
  soften verifier results.
- Any “evaluation run” record stores verifier outputs by reference or exact copy;
  it must not invent alternate scores.

## Shared tool surface

Model runners will use the **same 12-tool surface** already exposed to evaluated
agents for the approved release, workspace, telemetry, state, runtime, and
recovery interfaces.

- No privileged adapters, hidden workloads, gold assets, or verifier internals
  are exposed to model runners through the tool gateway.
- Tool availability and schemas stay aligned with the trial evaluation contract.

## Planned model adapter interface

A narrow adapter interface (conceptual) will:

1. Accept a model identity, provider config reference, and evaluation-run id.
2. Drive the episode only through the shared 12-tool gateway.
3. Stream or batch tool calls/responses into an immutable run transcript.
4. Request final grading exclusively via the strict verifier entrypoint.
5. Persist the verifier receipt and transcript under the evaluation-run record.

Adapters must not open unrestricted shell, filesystem, network, or database
inspection paths beyond the approved tool surface.

## Planned provider support

Provider support is planned behind the adapter interface, for example:

- Local or scripted baseline runners (deterministic fixtures / oracle paths for
  engineering checks only; never confused with submission scoring authority).
- Hosted chat/completion providers selected at run configuration time.

Provider credentials stay outside the repository and outside agent-visible
runtime metadata. Provider choice must not alter verifier predicates.

## Immutable evaluation-run records

Each evaluation run should produce an append-only record containing at least:

- run id, timestamp, environment commit SHA, and pair/instance identifiers that
  are safe to expose;
- selected model/provider identifiers (non-secret);
- transcript of tool interactions;
- exact verifier receipt (or content-addressed pointer);
- outcome fields copied from the verifier without transformation.

Records must not store secrets, privileged member selectors, gold patches, or
hidden causal values.

## Planned Next.js dashboard

A separate Next.js app will present:

- model/provider selection for launching runs;
- run history and receipt inspection;
- comparison views across models and instances.

The browser never calls the verifier directly with authority to mutate scores.
It talks to an evaluation service that orchestrates runners and stores records.

## Planned Motion for React animations

Motion for React will be used for deliberate UI presence and hierarchy (run
state transitions, result reveal, comparison emphasis)—not for decorative noise
or artificial waiting that could be mistaken for evaluation progress.

## Planned Chart.js comparisons

Chart.js will visualize cross-model comparisons (pass rates, horizon length
proxies where already measured, failure predicate frequencies) derived strictly
from stored verifier receipts and run metadata.

Charts are presentation only; they do not score.

## Proposed folders

```text
apps/dashboard              # Next.js UI (version two)
src/model_runners           # provider adapters + runner orchestration
src/evaluation_service      # run lifecycle, record persistence, gateway wiring
```

Existing trial packages under `src/` for the environment and verifier remain the
scoring and substrate authority. New v2 folders must not import privileged
grading assets into the browser bundle.

## Security boundary

```text
Browser (Next.js)
  -> Evaluation service (authn/z, run control, record store)
    -> Model runner (provider I/O)
      -> Tool gateway (approved 12-tool surface only)
        -> Environment runtime
    -> Strict verifier (sole scoring authority; no reward mutation elsewhere)
```

Hard rules:

- Browser code cannot reach verifier internals, hidden assets, or canonical
  grading roots.
- Model runners cannot bypass the tool gateway.
- The evaluation service may invoke the verifier but must not alter its outputs.
- APEX-SWE remains an external reference under the parent platform `references/`
  tree; it is not merged into this environment repository.

## Advancement rule

No model-evaluation feature ships as part of `trial-submission-v1`. Work proceeds
only on version-two branches (starting with `feature/model-evaluation-dashboard`)
with explicit approval for later implementation milestones.
