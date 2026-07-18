"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Activity, BarChart3, FlaskConical, Gauge, History, Menu, Moon, Radar, Settings, Sun, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Batch } from "@/lib/types";
import { MotionButton, PageTransition, SharedSelectionIndicator, motionTransition } from "@/components/motion";

const links = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/evaluations/new", label: "New evaluation", icon: FlaskConical },
  { href: "/runs", label: "Runs", icon: History },
  { href: "/compare", label: "Compare", icon: BarChart3 },
  { href: "/talon", label: "Talon simulation", icon: Radar },
  { href: "/settings", label: "Settings", icon: Settings },
];

const terminalStatuses = new Set(["completed", "completed_with_errors", "cancelled", "interrupted"]);

export function ThemeToggle() {
  const [theme, setTheme] = useState("dark");
  useEffect(() => {
    const saved = localStorage.getItem("frontier-theme");
    const next = saved ?? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.dataset.theme = next;
    setTheme(next);
  }, []);
  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    localStorage.setItem("frontier-theme", next);
  }
  const Icon = theme === "dark" ? Sun : Moon;
  return <MotionButton className="icon-button" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}><Icon size={16} aria-hidden="true" /></MotionButton>;
}

function GlobalRunStatus() {
  const [active, setActive] = useState<Batch[]>([]);
  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const result = await api<{ items: Batch[] }>("/api/evaluations?limit=40");
        if (mounted) setActive(result.items.filter(batch => !terminalStatuses.has(batch.status)));
      } catch {
        if (mounted) setActive([]);
      }
    }
    void load();
    const interval = window.setInterval(() => void load(), 5000);
    return () => { mounted = false; window.clearInterval(interval); };
  }, []);
  const content = <><Activity size={14} aria-hidden="true" /><span>{active.length ? `${active.length} active batch${active.length === 1 ? "" : "es"}` : "No active runs"}</span></>;
  return active[0]
    ? <Link className="global-run-status active" href="/runs" aria-live="polite">{content}</Link>
    : <span className="global-run-status" aria-live="polite">{content}</span>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const reduce = useReducedMotion();
  const [open, setOpen] = useState(false);
  const talon = pathname.startsWith("/talon");

  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    function close(event: KeyboardEvent) { if (event.key === "Escape") setOpen(false); }
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className={open ? "sidebar open" : "sidebar"} aria-label="Application sidebar">
        <div className="brand">
          <span className="brand-mark">F/</span>
          <span><strong>Frontier</strong><small>Evaluation control</small></span>
          <MotionButton className="icon-button sidebar-close" aria-label="Close navigation" onClick={() => setOpen(false)}><X size={17} aria-hidden="true" /></MotionButton>
        </div>
        <nav aria-label="Primary navigation">
          {links.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link key={href} href={href} className={active ? "nav-link active" : "nav-link"} aria-current={active ? "page" : undefined}>
                {active && <SharedSelectionIndicator layoutId="primary-navigation" />}
                <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
                <span className="nav-label">{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-foot"><span className="status-dot ok" /><span>Local control plane</span></div>
      </aside>
      <AnimatePresence>
        {open && <motion.button className="scrim" aria-label="Close navigation" onClick={() => setOpen(false)} initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={motionTransition} />}
      </AnimatePresence>
      <section className="main-column">
        <header className="topbar">
          <MotionButton className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={18} aria-hidden="true" /></MotionButton>
          <div className="topbar-context"><span className="eyebrow">{talon ? "Talon decision lab" : "Model evaluation"}</span><span className="authority-pill">{talon ? "Simulation · human approval" : "Strict verifier authority"}</span></div>
          <div className="topbar-actions"><GlobalRunStatus /><ThemeToggle /></div>
        </header>
        <main id="main-content" className="page" tabIndex={-1}>
          <PageTransition routeKey={pathname}>{children}</PageTransition>
        </main>
      </section>
    </div>
  );
}
