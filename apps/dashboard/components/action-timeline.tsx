"use client";

import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import type { TimelineEntry } from "@/lib/types";
import { duration } from "@/lib/format";

export function ActionTimeline({ entries }: { entries: TimelineEntry[] }) {
  const [visible, setVisible] = useState(40);
  const reduce = useReducedMotion();
  if (!entries.length) return <p className="muted">No authenticated actions were recorded.</p>;
  return <div className="timeline">
    {entries.slice(0, visible).map(entry => <motion.article className="timeline-entry" key={entry.sequence} initial={reduce ? false : { opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }}>
      <div className={entry.success ? "timeline-node ok" : "timeline-node fail"}>{entry.sequence}</div>
      <div className="timeline-body">
        <div className="timeline-head"><code>{entry.tool}</code><span>tick {entry.fake_tick ?? "—"} · {duration(entry.duration_ms)}</span></div>
        <details><summary>Sanitized request and result</summary><div className="code-grid"><pre>{JSON.stringify(entry.arguments, null, 2)}</pre><pre>{JSON.stringify(entry.result_summary, null, 2)}</pre></div></details>
        <div className="timeline-meta"><span>{entry.request_bytes} B request</span><span>{entry.response_bytes} B response</span>{entry.error_code && <span className="danger">{entry.error_code}</span>}{entry.terminated && <span className="success">terminated</span>}{entry.truncated && <span className="warning">truncated</span>}</div>
      </div>
    </motion.article>)}
    {visible < entries.length && <button className="button secondary" onClick={() => setVisible(value => value + 40)}>Show more actions</button>}
  </div>;
}
