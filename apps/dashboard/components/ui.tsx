"use client";

import Link from "next/link";
import { Check, Clipboard, Inbox, LoaderCircle, ShieldCheck, TriangleAlert } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { number, percent, shortHash } from "@/lib/format";
import { AnimatedCard, AnimatedNumber, AnimatedStatus, ExpandablePanel, MotionButton } from "@/components/motion";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  const reduce = useReducedMotion();
  return <motion.header className="page-header" initial={reduce ? false : { opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{actions && <div className="header-actions">{actions}</div>}</motion.header>;
}

export function MetricCard({
  label,
  value,
  detail,
  tone = "neutral",
  emphasis = false,
  numericValue,
  format,
}: {
  label: string;
  value?: ReactNode;
  detail?: string;
  tone?: string;
  emphasis?: boolean;
  numericValue?: number | null;
  format?: (value: number) => string;
}) {
  return <AnimatedCard className={`metric-card tone-${tone}${emphasis ? " emphasized" : ""}`}><span>{label}</span><strong>{numericValue !== undefined ? <AnimatedNumber value={numericValue} format={format} /> : value}</strong>{detail && <small>{detail}</small>}</AnimatedCard>;
}

export function RunStatusBadge({ status }: { status: string }) {
  const label = status.replaceAll("_", " ");
  return <span className={`status-badge status-${status.replaceAll("_", "-")}`}><span className="status-dot" /><AnimatedStatus state={status}>{label}</AnimatedStatus></span>;
}

export function ProviderBadge({ provider }: { provider: string }) {
  return <span className="provider-badge">{provider}</span>;
}

export function CommitBadge({ value, label = "commit" }: { value?: string; label?: string }) {
  return <span className="commit-badge" title={value}><span>{label}</span><code>{shortHash(value)}</code></span>;
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return <section className="empty-state"><div className="empty-glyph" aria-hidden="true"><Inbox size={22} /></div><h2>{title}</h2><p>{detail}</p>{action}</section>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <section className="error-state" role="alert"><TriangleAlert size={19} aria-hidden="true" /><div><strong>Unable to load this view</strong><p>{message}</p>{retry && <MotionButton className="button secondary" onClick={retry}>Try again</MotionButton>}</div></section>;
}

export function LoadingState({ rows = 3, label = "Loading dashboard data" }: { rows?: number; label?: string }) {
  return <div className="loading-stack" role="status" aria-label={label}>{Array.from({ length: rows }, (_, index) => <div className="skeleton" key={index} aria-hidden="true" />)}<span className="sr-only">{label}</span></div>;
}

export function InlineLoading({ label }: { label: string }) {
  return <span className="inline-loading" role="status"><LoaderCircle size={14} className="spin" aria-hidden="true" />{label}</span>;
}

export function AuthorityNotice() {
  return <aside className="authority-notice"><ShieldCheck size={19} aria-hidden="true" /><p><strong>Scores are read-only.</strong> This interface displays results produced by the existing strict verifier; it never calculates or overrides reward.</p></aside>;
}

export function BatchProgress({ total, completed, failed, cancelled }: { total: number; completed: number; failed: number; cancelled: number }) {
  const finished = completed + failed + cancelled;
  const ratio = total ? finished / total : 0;
  const reduce = useReducedMotion();
  return <div className="batch-progress"><div className="progress-label"><span>{finished} of {total} episodes settled</span><strong>{percent(ratio)}</strong></div><div className="progress-track" role="progressbar" aria-valuenow={finished} aria-valuemin={0} aria-valuemax={total} aria-label="Overall batch progress"><motion.div className="progress-fill" initial={reduce ? false : { scaleX: 0 }} animate={{ scaleX: ratio }} style={{ transformOrigin: "left" }} /></div></div>;
}

export function BudgetProgress({ label, value, limit, format = valueToFormat => number(valueToFormat, 0) }: { label: string; value: number; limit?: number | null; format?: (value: number) => string }) {
  if (!limit) return <div className="budget-row"><div><span>{label}</span><strong>{format(value)}</strong></div><span className="muted">No configured limit</span></div>;
  const ratio = Math.min(1, value / limit);
  return <div className="budget-row"><div><span>{label}</span><strong>{format(value)} / {format(limit)}</strong></div><div className="mini-progress" role="progressbar" aria-label={`${label} budget`} aria-valuenow={value} aria-valuemin={0} aria-valuemax={limit}><motion.span animate={{ scaleX: ratio }} style={{ transformOrigin: "left" }} /></div></div>;
}

export function CompatibilityWarning({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return <aside className="compatibility-warning" role="alert"><TriangleAlert size={19} aria-hidden="true" /><div><strong>Not a like-for-like leaderboard</strong><ul>{warnings.map(warning => <li key={warning}>{warning}</li>)}</ul></div></aside>;
}

export function DataTable({ headers, rows, caption }: { headers: string[]; rows: ReactNode[][]; caption: string }) {
  return <div className="table-scroll" tabIndex={0}><table><caption className="sr-only">{caption}</caption><thead><tr>{headers.map(header => <th key={header} scope="col">{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
}

export function EpisodeCard({ run }: { run: { run_id: string; provider: string; model: string; seed: number; attempt: number; status: string; current_step?: number; current_tool?: string; authoritative_reward?: number | null; input_tokens?: number; output_tokens?: number } }) {
  return <AnimatedCard className="episode-card"><ExpandablePanel summary={<div className="episode-summary"><div><code>{run.run_id.slice(0, 18)}</code><span>seed {run.seed} · attempt {run.attempt}</span></div><RunStatusBadge status={run.status} /></div>} defaultOpen={run.status === "running"}>
    <div className="episode-model"><ProviderBadge provider={run.provider} /><strong>{run.model}</strong></div>
    <dl className="episode-stats"><div><dt>Step</dt><dd>{run.current_step ?? "—"}</dd></div><div><dt>Tool</dt><dd><code>{run.current_tool ?? "—"}</code></dd></div><div><dt>Tokens</dt><dd>{number((run.input_tokens ?? 0) + (run.output_tokens ?? 0), 0)}</dd></div><div><dt>Score</dt><dd>{run.authoritative_reward ?? "—"}</dd></div></dl>
    <Link className="text-link" href={`/runs/${run.run_id}`}>Inspect episode</Link>
  </ExpandablePanel></AnimatedCard>;
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }
  return <MotionButton className="icon-text-button" onClick={copy} aria-label={`${label} to clipboard`}>{copied ? <Check size={14} aria-hidden="true" /> : <Clipboard size={14} aria-hidden="true" />}<span>{copied ? "Copied" : label}</span></MotionButton>;
}

export function ConfirmDialog({ open, title, detail, confirmLabel, cancelLabel = "Keep running", onConfirm, onClose }: { open: boolean; title: string; detail: string; confirmLabel: string; cancelLabel?: string; onConfirm: () => void; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return <dialog ref={ref} className="dialog" onCancel={onClose} onClose={onClose}><div className="dialog-content"><span className="eyebrow">Confirmation</span><h2>{title}</h2><p>{detail}</p><div className="dialog-actions"><MotionButton className="button secondary" onClick={onClose}>{cancelLabel}</MotionButton><MotionButton className="button danger-button" onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</MotionButton></div></div></dialog>;
}
