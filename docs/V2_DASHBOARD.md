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

## Visual and motion system

The dashboard keeps surface, border, text, status, focus, spacing, radius, shadow,
duration, easing, and chart values in the global CSS token layer. Light and dark
themes use the same semantic tokens; hashes, IDs, tool names, and code are the only
monospaced content. A provider/model pair receives a deterministic colour from the
shared chart palette, so it keeps the same identity across every comparison view.

Reusable Motion for React primitives provide page transitions, hover/tap feedback,
animated values and statuses, shared selection indicators, staggered first render,
and expandable regions. Normal transitions stay between 160 and 240 ms and layout
transitions between 240 and 360 ms. Live refreshes do not animate whole lists, SSE
refreshes are throttled, and chart animation is disabled for large datasets.

When `prefers-reduced-motion: reduce` is active, movement and scale feedback are
removed. Controls, focus feedback, data, and expanded content remain immediately
available, with only minimal opacity changes where needed for state continuity.

## Accessibility and supported browsers

Navigation, provider/model choices, filters, segmented controls, dialogs, and
expandable records are keyboard operable with visible focus rings. Provider and
model radio groups support arrow, Home, and End keys. Status changes use text and
screen-reader announcements in addition to colour. Native modal dialogs provide
focus containment and Escape-to-close behavior. Each comparison chart has a named
table equivalent; the whole comparison surface can switch to table mode, and CSV
exports contain the currently displayed chart data.

The supported local-development browsers are current stable Chrome, Edge, Firefox,
and Safari releases with native `dialog`, CSS custom property, and ES2022 support.
The automated browser suite runs on Playwright Chromium. Known limitations: timeline
rendering is progressive rather than virtualized, Chart.js canvases do not expose
individual points directly to screen readers (use the adjacent table), model search
is local to already discovered models, and full live-state transitions can be brief
for the deterministic scripted provider.
