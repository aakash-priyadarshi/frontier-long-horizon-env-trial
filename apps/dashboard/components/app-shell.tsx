"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";

const links = [
  ["/", "Overview", "⌂"],
  ["/evaluations/new", "New evaluation", "+"],
  ["/compare", "Compare", "⌁"],
  ["/settings", "Settings", "⚙"],
];

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
  return <button className="icon-button" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>{theme === "dark" ? "☼" : "◐"}</button>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const reduce = useReducedMotion();
  const [open, setOpen] = useState(false);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className={open ? "sidebar open" : "sidebar"}>
        <div className="brand">
          <span className="brand-mark">F/</span>
          <span><strong>Frontier</strong><small>Evaluation control</small></span>
        </div>
        <nav aria-label="Primary navigation">
          {links.map(([href, label, icon]) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return <Link key={href} href={href} className={active ? "nav-link active" : "nav-link"} onClick={() => setOpen(false)}><span aria-hidden="true">{icon}</span>{label}</Link>;
          })}
        </nav>
        <div className="sidebar-foot"><span className="status-dot ok" />Local control plane</div>
      </aside>
      {open && <button className="scrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <section className="main-column">
        <header className="topbar">
          <button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setOpen(true)}>☰</button>
          <div className="topbar-context"><span className="eyebrow">Model evaluation</span><span className="authority-pill">Strict verifier authority</span></div>
          <ThemeToggle />
        </header>
        <motion.main id="main-content" className="page" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reduce ? 0 : 0.22 }} key={pathname}>
          {children}
        </motion.main>
      </section>
    </div>
  );
}
