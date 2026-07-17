"use client";

import { AlertTriangle, CheckCircle2, CircleAlert, GitBranch, Search } from "lucide-react";
import type { ModelTurnDebug, ToolUseDebug, ToolUseFinding } from "@/lib/types";
import { EmptyState } from "@/components/ui";

function severityIcon(severity: ToolUseFinding["severity"]) {
  if (severity === "error") return <CircleAlert size={15} className="danger" aria-hidden="true" />;
  return <AlertTriangle size={15} className="warning" aria-hidden="true" />;
}

function phaseTone(status: string) {
  if (status === "present") return "ok";
  if (status === "attempted") return "warn";
  return "miss";
}

export function ToolUseDebugPanel({
  debug,
  modelTurns,
}: {
  debug?: ToolUseDebug | null;
  modelTurns?: ModelTurnDebug[] | null;
}) {
  if (!debug) {
    return <EmptyState title="Tool-use debug unavailable" detail="This episode has no authenticated timeline to analyze yet." />;
  }
  return (
    <div className="tool-debug-shell">
      <div className={`tool-debug-summary tone-${debug.primary_cause?.severity ?? "ok"}`}>
        <div>
          <span className="eyebrow">Root-cause verdict</span>
          <strong>{debug.summary}</strong>
          {debug.primary_cause && (
            <p>
              <code>{debug.primary_cause.code}</code>
              {debug.primary_cause.tool ? <> · step {debug.primary_cause.sequence} · <code>{debug.primary_cause.tool}</code></> : null}
            </p>
          )}
        </div>
        <dl>
          <div><dt>Tool protocol</dt><dd>{debug.protocol_health.tool_calling_appears_functional ? "functional" : "broken / absent"}</dd></div>
          <div><dt>Executed / failed</dt><dd>{debug.protocol_health.tool_calls_executed} / {debug.protocol_health.tool_failures}</dd></div>
          <div><dt>Model calls</dt><dd>{debug.protocol_health.model_calls}</dd></div>
          <div><dt>Reasoning tokens</dt><dd>{debug.protocol_health.reasoning_tokens}</dd></div>
        </dl>
      </div>

      <div className="tool-debug-grid">
        <section>
          <div className="section-head"><div><span className="eyebrow">Workflow coverage</span><h3>Expected repair phases</h3></div></div>
          <ol className="tool-debug-phases">
            {debug.workflow_phases.map(phase => (
              <li className={`phase-${phaseTone(phase.status)}`} key={phase.id}>
                <div>
                  <strong>{phase.title}</strong>
                  <span>{phase.detail}</span>
                </div>
                <code>{phase.status}</code>
              </li>
            ))}
          </ol>
          <div className="tool-debug-path">
            <span><GitBranch size={13} aria-hidden="true" /> Shortest valid path</span>
            <ol>{debug.expected_shortest_path.map(step => <li key={step}><code>{step}</code></li>)}</ol>
          </div>
        </section>

        <section>
          <div className="section-head"><div><span className="eyebrow">Findings</span><h3>Classified failures</h3></div><span className="muted">{debug.findings.length}</span></div>
          {!debug.findings.length ? (
            <p className="success"><CheckCircle2 size={14} aria-hidden="true" /> No precondition or protocol findings.</p>
          ) : (
            <ul className="tool-debug-findings">
              {debug.findings.map((finding, index) => (
                <li key={`${finding.code}-${finding.sequence ?? "x"}-${index}`}>
                  <div className="tool-debug-finding-head">
                    {severityIcon(finding.severity)}
                    <strong>{finding.title}</strong>
                    <code>{finding.code}</code>
                  </div>
                  <p>{finding.detail}</p>
                  <small>Fix: {finding.remediation}</small>
                  {(finding.tool || finding.sequence != null) && (
                    <span className="muted">
                      {finding.sequence != null ? `step ${finding.sequence}` : null}
                      {finding.tool ? <> · <code>{finding.tool}</code></> : null}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="tool-debug-coverage">
        {Object.entries(debug.coverage).map(([name, count]) => (
          <div key={name}><span>{name}</span><strong>{count}</strong></div>
        ))}
      </div>

      {!!modelTurns?.length && (
        <section className="tool-debug-turns">
          <div className="section-head"><div><span className="eyebrow">Provider turns</span><h3>Model turn debug</h3></div><span className="muted"><Search size={13} aria-hidden="true" /> finish_reason · tool names · token split</span></div>
          <div className="tool-debug-turn-table-wrap">
            <table>
              <caption>Per-turn provider metadata</caption>
              <thead>
                <tr>
                  <th>Turn</th>
                  <th>Finish</th>
                  <th>Tools</th>
                  <th>Names</th>
                  <th>Dropped</th>
                  <th>Text</th>
                  <th>In</th>
                  <th>Out</th>
                  <th>Reasoning</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {modelTurns.map(turn => (
                  <tr key={turn.turn} className={turn.tool_call_count === 0 ? "tone-warn" : undefined}>
                    <td>{turn.turn}</td>
                    <td><code>{turn.finish_reason ?? "—"}</code></td>
                    <td>{turn.tool_call_count}</td>
                    <td><code>{turn.tool_names.length ? turn.tool_names.join(", ") : "—"}</code></td>
                    <td>{turn.dropped_tool_calls}</td>
                    <td>{turn.has_text ? `${turn.text_chars} chars` : "—"}</td>
                    <td>{turn.input_tokens}</td>
                    <td>{turn.output_tokens}</td>
                    <td>{turn.reasoning_tokens || turn.reasoning_chars ? `${turn.reasoning_tokens} tok / ${turn.reasoning_chars} chars` : "—"}</td>
                    <td>{Math.round(turn.latency_ms)} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
