"use client";

import { CheckCircle2, CircleAlert, Pause, Play, TerminalSquare } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { TimelineEntry } from "@/lib/types";
import { duration } from "@/lib/format";
import { ExpandablePanel, MotionButton } from "@/components/motion";
import { CopyButton, EmptyState } from "@/components/ui";

type Category = "all" | "diagnostics" | "recovery" | "workspace" | "release" | "verification";

const filters: Array<{ id: Category; label: string }> = [
  { id: "all", label: "All" },
  { id: "diagnostics", label: "Diagnostics" },
  { id: "recovery", label: "Recovery" },
  { id: "workspace", label: "Workspace" },
  { id: "release", label: "Release" },
  { id: "verification", label: "Verification" },
];

export function toolCategory(tool: string): Exclude<Category, "all"> {
  if (tool.startsWith("recovery.")) return "recovery";
  if (tool.startsWith("workspace.")) return "workspace";
  if (tool.startsWith("release.")) return "release";
  if (tool.startsWith("runtime.")) return "verification";
  return "diagnostics";
}

export function ActionTimeline({ entries, live = false }: { entries: TimelineEntry[]; live?: boolean }) {
  const [visible, setVisible] = useState(40);
  const [filter, setFilter] = useState<Category>("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  const filtered = useMemo(() => entries.filter(entry => filter === "all" || toolCategory(entry.tool) === filter), [entries, filter]);
  const shown = filtered.slice(0, visible);

  useEffect(() => {
    if (live && autoScroll && shown.length === filtered.length) endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [autoScroll, entries.length, filtered.length, live, shown.length]);

  if (!entries.length) return <EmptyState title="No authenticated actions" detail="The episode has not produced a sanitized environment-tool record yet." />;
  return <div className="timeline-shell">
    <div className="timeline-toolbar">
      <div className="timeline-filters" role="tablist" aria-label="Timeline category">
        {filters.map(item => <MotionButton role="tab" aria-selected={filter === item.id} className={filter === item.id ? "filter-tab active" : "filter-tab"} key={item.id} onClick={() => { setFilter(item.id); setVisible(40); }}>{item.label}<span>{item.id === "all" ? entries.length : entries.filter(entry => toolCategory(entry.tool) === item.id).length}</span></MotionButton>)}
      </div>
      {live && <MotionButton className="icon-text-button" aria-pressed={!autoScroll} onClick={() => setAutoScroll(value => !value)}>{autoScroll ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}{autoScroll ? "Pause auto-scroll" : "Resume auto-scroll"}</MotionButton>}
    </div>
    {!filtered.length ? <EmptyState title="No matching actions" detail={`No authenticated timeline entries are categorized as ${filter}.`} /> : <div className="timeline">
      {shown.map((entry, index) => {
        const category = toolCategory(entry.tool);
        const current = live && index === shown.length - 1 && shown.length === filtered.length;
        const request = JSON.stringify(entry.arguments, null, 2);
        const result = JSON.stringify(entry.result_summary, null, 2);
        return <article className={`timeline-entry${current ? " current" : ""}`} key={entry.sequence}>
          <div className={entry.success ? "timeline-node ok" : "timeline-node fail"}>{entry.sequence}</div>
          <div className="timeline-body">
            <ExpandablePanel summary={<div className="timeline-summary"><div><span className="timeline-kind"><TerminalSquare size={13} aria-hidden="true" />Environment tool · {category}</span><code>{entry.tool}</code></div><div className="timeline-state">{entry.success ? <CheckCircle2 size={15} className="success" aria-hidden="true" /> : <CircleAlert size={15} className="danger" aria-hidden="true" />}<span>{entry.success ? "Completed" : "Failed"}</span><strong>{duration(entry.duration_ms)}</strong></div></div>}>
              <div className="timeline-detail-head"><span>Sanitized request and result</span><div><CopyButton value={request} label="Copy request" /><CopyButton value={result} label="Copy result" /></div></div>
              <div className="code-grid"><div><span>Request arguments</span><pre>{request}</pre></div><div><span>Result summary</span><pre>{result}</pre></div></div>
            </ExpandablePanel>
            <div className="timeline-meta"><span>tick {entry.fake_tick ?? "—"}</span><span>{entry.request_bytes} B request</span><span>{entry.response_bytes} B response</span>{entry.error_code && <span className="danger">{entry.error_code}</span>}{entry.terminated && <span className="success">terminated</span>}{entry.truncated && <span className="warning">truncated</span>}{current && <span className="current-step-label">Current step</span>}</div>
          </div>
        </article>;
      })}
      <div ref={endRef} />
    </div>}
    {visible < filtered.length && <MotionButton className="button secondary timeline-more" onClick={() => setVisible(value => value + 40)}>Show {Math.min(40, filtered.length - visible)} more actions</MotionButton>}
  </div>;
}
