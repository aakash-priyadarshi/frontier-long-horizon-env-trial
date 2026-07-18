import Link from "next/link";
import { AlertTriangle, Database, FlaskConical, Gauge, GitCompare, GraduationCap, ListChecks, ShieldCheck } from "lucide-react";

export const talonLinks = [
  { href: "/talon", label: "Overview", icon: Gauge },
  { href: "/talon/scenarios", label: "Scenarios", icon: ListChecks },
  { href: "/talon/datasets", label: "Datasets", icon: Database },
  { href: "/talon/training/new", label: "Train", icon: GraduationCap },
  { href: "/talon/models", label: "Models", icon: FlaskConical },
  { href: "/talon/evaluations/new", label: "Evaluate", icon: ShieldCheck },
  { href: "/talon/compare", label: "Compare", icon: GitCompare },
  { href: "/talon/policy", label: "Policy", icon: AlertTriangle },
];

export function TalonBoundaryNotice() {
  return <aside className="talon-boundary"><ShieldCheck size={20} aria-hidden="true" /><div><strong>Simulation-only decision support</strong><p>Actions are abstract recommendations. The deterministic policy gate has no external effect, and human approval remains mandatory. No physical-response controls exist here.</p></div></aside>;
}

export function TalonSubnav() {
  return <nav className="talon-subnav" aria-label="Talon simulation navigation">{talonLinks.map(({ href, label, icon: Icon }) => <Link href={href} key={href}><Icon size={15} aria-hidden="true" />{label}</Link>)}</nav>;
}
