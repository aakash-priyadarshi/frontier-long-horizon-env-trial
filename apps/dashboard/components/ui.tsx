"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { number, percent, shortHash } from "@/lib/format";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: React.ReactNode }) {
  return <div className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{actions && <div className="header-actions">{actions}</div>}</div>;
}

export function MetricCard({ label, value, detail, tone = "neutral" }: { label: string; value: React.ReactNode; detail?: string; tone?: string }) {
  const reduce = useReducedMotion();
  return <motion.article className={`metric-card tone-${tone}`} layout={!reduce}><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</motion.article>;
}

export function RunStatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status.replaceAll("_", "-")}`}><span className="status-dot" />{status.replaceAll("_", " ")}</span>;
}

export function ProviderBadge({ provider }: { provider: string }) {
  return <span className="provider-badge">{provider}</span>;
}

export function CommitBadge({ value, label = "commit" }: { value?: string; label?: string }) {
  return <span className="commit-badge" title={value}><span>{label}</span><code>{shortHash(value)}</code></span>;
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return <section className="empty-state"><div className="empty-glyph" aria-hidden="true">◇</div><h2>{title}</h2><p>{detail}</p>{action}</section>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <section className="error-state" role="alert"><strong>Unable to load this view</strong><p>{message}</p>{retry && <button className="button secondary" onClick={retry}>Try again</button>}</section>;
}

export function LoadingState({ rows = 3 }: { rows?: number }) {
  return <div className="loading-stack" aria-label="Loading">{Array.from({ length: rows }, (_, index) => <div className="skeleton" key={index} />)}</div>;
}

export function AuthorityNotice() {
  return <aside className="authority-notice"><span aria-hidden="true">◆</span><p><strong>Scores are read-only.</strong> This interface displays results produced by the existing strict verifier; it never calculates or overrides reward.</p></aside>;
}

export function BatchProgress({ total, completed, failed, cancelled }: { total: number; completed: number; failed: number; cancelled: number }) {
  const finished = completed + failed + cancelled;
  const ratio = total ? finished / total : 0;
  return <div className="batch-progress"><div className="progress-label"><span>{finished} of {total} episodes settled</span><strong>{percent(ratio)}</strong></div><div className="progress-track" role="progressbar" aria-valuenow={finished} aria-valuemin={0} aria-valuemax={total}><motion.div className="progress-fill" initial={{ width: 0 }} animate={{ width: `${ratio * 100}%` }} /></div></div>;
}

export function CompatibilityWarning({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return <aside className="compatibility-warning" role="alert"><strong>Not a like-for-like leaderboard</strong><ul>{warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></aside>;
}

export function DataTable({ headers, rows, caption }: { headers: string[]; rows: React.ReactNode[][]; caption: string }) {
  return <div className="table-scroll"><table><caption className="sr-only">{caption}</caption><thead><tr>{headers.map(header => <th key={header} scope="col">{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
}

export function EpisodeCard({ run }: { run: { run_id: string; provider: string; model: string; seed: number; attempt: number; status: string; current_step?: number; current_tool?: string; authoritative_reward?: number | null; input_tokens?: number; output_tokens?: number } }) {
  return <motion.article className="episode-card" layout><div className="episode-head"><div><code>{run.run_id.slice(0, 18)}</code><span>seed {run.seed} · attempt {run.attempt}</span></div><RunStatusBadge status={run.status} /></div><div className="episode-model"><ProviderBadge provider={run.provider} /><strong>{run.model}</strong></div><dl className="episode-stats"><div><dt>Step</dt><dd>{run.current_step ?? "—"}</dd></div><div><dt>Tool</dt><dd><code>{run.current_tool ?? "—"}</code></dd></div><div><dt>Tokens</dt><dd>{number((run.input_tokens ?? 0) + (run.output_tokens ?? 0), 0)}</dd></div><div><dt>Score</dt><dd>{run.authoritative_reward ?? "—"}</dd></div></dl><Link className="text-link" href={`/runs/${run.run_id}`}>Inspect episode →</Link></motion.article>;
}
