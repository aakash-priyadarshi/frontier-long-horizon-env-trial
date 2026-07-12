# AGENTS.md

## Project purpose

This repository is an original hiring-trial build for a long-horizon RL
environment targeting a specific capability gap in frontier coding or
software-engineering agents.

The project is currently in the research and proposal stage. Do not begin
implementing an environment until the capability gap and verifier approach
have been reviewed and approved.

## Originality and IP rules

This repository must contain only original work created for this trial.

Do not copy or adapt:

- code from previous clients
- private evaluation tasks
- previous RL environments
- prior client generators or verifiers
- private metrics, receipts, reports, names, or file structures
- proprietary datasets or task instances

General engineering lessons may inform decisions, but all task concepts,
code, generators, verifiers, tests, and evidence must be newly created here.

Do not mention previous clients or private repositories anywhere in committed
files.

## Research rules

Research must focus on a specific and current capability weakness in frontier
coding or agent models.

Every proposed gap must include:

1. A precise capability name.
2. The exact expected model failure mode.
3. Primary supporting sources.
4. What the sources demonstrate and what they do not demonstrate.
5. Why users and frontier labs care.
6. The closest existing benchmarks.
7. Why those benchmarks do not already test the same capability.
8. A possible automated verifier.
9. A contamination argument.
10. A credible path to a genuine long-horizon environment.

Do not invent citations, model scores, benchmark results, or claims.

Clearly distinguish:

- sourced facts
- interpretation
- assumptions
- unresolved questions

Prefer papers, official benchmark repositories, model cards, and technical
reports over blogs or secondary summaries.

## Research output location

When research begins, create:

```text
research/
├── sources.md
├── candidate-gaps.md
└── benchmark-comparison.md