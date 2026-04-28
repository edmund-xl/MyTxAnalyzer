"use client";

import Link from "next/link";
import { Activity, FileText, GitBranch, LayoutDashboard, ShieldCheck } from "lucide-react";
import type { Role } from "@/lib/api";

export type ShellCaseTab = "overview" | "diagrams" | "findings" | "reports" | "jobs";

export function Shell({
  children,
  role,
  onRoleChange,
  activeCaseTab,
  onCaseTabChange,
  caseNavCaseId
}: {
  children: React.ReactNode;
  role: Role;
  onRoleChange: (role: Role) => void;
  activeCaseTab?: ShellCaseTab;
  onCaseTabChange?: (tab: ShellCaseTab) => void;
  caseNavCaseId?: string;
}) {
  const caseNavItems: Array<{ tab: ShellCaseTab; label: string; icon: React.ReactNode }> = [
    { tab: "diagrams", label: "Diagrams", icon: <GitBranch size={17} /> },
    { tab: "findings", label: "Findings", icon: <ShieldCheck size={17} /> },
    { tab: "reports", label: "Reports", icon: <FileText size={17} /> },
    { tab: "jobs", label: "Jobs", icon: <Activity size={17} /> }
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">RCA Workbench</div>
        <nav className="nav">
          <Link className={`nav-item ${activeCaseTab ? "" : "active"}`} href="/">
            <LayoutDashboard size={17} /> Dashboard
          </Link>
          {caseNavItems.map((item) =>
            onCaseTabChange ? (
              <button key={item.tab} className={`nav-item nav-button ${activeCaseTab === item.tab ? "active" : ""}`} onClick={() => onCaseTabChange(item.tab)}>
                {item.icon} {item.label}
              </button>
            ) : caseNavCaseId ? (
              <Link key={item.tab} className="nav-item" href={`/cases/${caseNavCaseId}?tab=${item.tab}`}>
                {item.icon} {item.label}
              </Link>
            ) : (
              <div key={item.tab} className="nav-item nav-item-disabled" aria-disabled="true">
                {item.icon} {item.label}
              </div>
            )
          )}
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <strong>On-chain RCA Workbench</strong>
          <select value={role} onChange={(event) => onRoleChange(event.target.value as Role)}>
            <option value="admin">admin</option>
            <option value="analyst">analyst</option>
            <option value="reviewer">reviewer</option>
            <option value="reader">reader</option>
          </select>
        </header>
        {children}
      </main>
    </div>
  );
}
