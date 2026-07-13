# V2 Dashboard

The App Router dashboard is a technical evaluation surface, not a generic admin
template. It provides dark and light themes, responsive navigation, keyboard focus,
semantic controls, monospaced identifiers, and `prefers-reduced-motion` behavior.

Routes:

- `/`: strict outcome overview, source binding, recent batches/failures, and a
  credential-free scripted empty state.
- `/evaluations/new`: capability-driven provider/model configuration, seed/attempt
  matrix, hard budgets, estimated episode count, and explicit confirmation.
- `/evaluations/[batchId]`: replayable live SSE progress, episode cards, usage, and
  cancellation.
- `/runs/[runId]`: authoritative score, verdict, digest, public workload outcomes,
  code-change summary, and progressively rendered sanitized action timeline.
- `/compare`: compatibility warnings, metric table, and reusable Chart.js views.
- `/settings`: browser-safe provider and runtime status.

Charts cover strict success, average/median reward, reward by seed, cost/reward,
actions/reward, outcomes, failed predicates, token usage, terminal reward
progression when present, and latency. Each chart is responsive, starts quantitative
axes at zero, has an accessible data/table companion where applicable, and exports
its displayed data. Missing cost or step-reward data gets an empty state—never a
fabricated value.

Motion for React is limited to page entry, layout/status transitions, timeline
appearance, progress, and chart surfaces. Controls are immediately available and
the reduced-motion media query removes effective animation duration.
