"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home, GitBranch, Play, Database, Package, Server,
  DollarSign, Settings, Layers, Cpu, Box
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type NavItem = { href: string; navKey: string; label: string; count: string | null; Icon: LucideIcon };

const NAV_BUILD: NavItem[] = [
  { href: "/",          navKey: "home",     label: "Home",         count: null,  Icon: Home },
  { href: "/workflows", navKey: "flows",    label: "Workflows",    count: "12",  Icon: GitBranch },
  { href: "/runs",      navKey: "runs",     label: "Runs",         count: "348", Icon: Play },
];
const NAV_REGISTRY: NavItem[] = [
  { href: "/registry",  navKey: "registry", label: "Base Models",  count: "47",  Icon: Package },
  { href: "/models",    navKey: "mymodels", label: "My Models",    count: null,  Icon: Box     },
  { href: "/datasets",  navKey: "datasets", label: "Datasets",     count: "23",  Icon: Database },
  { href: "/artifacts", navKey: "art",      label: "Artifacts",    count: null,  Icon: Layers  },
];
const NAV_OPERATE: NavItem[] = [
  { href: "/inference", navKey: "infer",    label: "Inference",    count: null,  Icon: Cpu },
  { href: "/endpoints", navKey: "deploy",   label: "Endpoints",    count: "8",   Icon: Server },
  { href: "/cost",      navKey: "cost",     label: "Cost & GPUs",  count: null,  Icon: DollarSign },
  { href: "/settings",  navKey: "settings", label: "Settings",     count: null,  Icon: Settings },
];

function NavRow({ href, label, count, Icon, active }: Omit<NavItem, "navKey"> & { active: boolean }) {
  return (
    <Link href={href} className={"op-nav-item" + (active ? " active" : "")} style={{ textDecoration: "none" }}>
      <span className="ic" style={{ display: "inline-flex", alignItems: "center" }}>
        <Icon size={15} strokeWidth={1.8} />
      </span>
      <span>{label}</span>
      {count && <span className="count">{count}</span>}
    </Link>
  );
}

export function Sidebar() {
  const path = usePathname();

  const isActive = (href: string, navKey: string) => {
    if (navKey === "home") return path === "/" || path === "/dashboard";
    if (href === "/") return path === "/";
    return path.startsWith(href);
  };

  const renderGroup = (title: string, items: NavItem[]) => (
    <>
      <div className="op-nav-section">{title}</div>
      {items.map(it => (
        <NavRow key={it.navKey} href={it.href} label={it.label} count={it.count} Icon={it.Icon} active={isActive(it.href, it.navKey)} />
      ))}
    </>
  );

  return (
    <aside className="op-sidebar">
      {/* Brand */}
      <div className="op-brand">
        <div className="op-brand-mark">op</div>
        <div className="op-brand-name">Orcha<span>pod</span></div>
      </div>

      {/* Workspace */}
      <div className="op-workspace">
        <div>
          <div className="ws-name">orbital-research</div>
          <div style={{ fontSize: 10.5, color: "var(--ink-3)", marginTop: 2 }}>9 members</div>
        </div>
        <div className="ws-tier">team</div>
      </div>

      {renderGroup("Build", NAV_BUILD)}
      {renderGroup("Registry", NAV_REGISTRY)}
      {renderGroup("Operate", NAV_OPERATE)}

      <div style={{ flex: 1 }} />

      {/* Budget widget */}
      <div style={{
        margin: "0 4px", padding: 12, borderRadius: 8,
        background: "linear-gradient(140deg, oklch(0.96 0.03 282), oklch(0.94 0.04 320))",
        border: "1px solid var(--line)", fontSize: 12,
      }}>
        <div style={{ fontWeight: 600, color: "var(--ink-1)", marginBottom: 4 }}>$28.40 used / $250</div>
        <div style={{ height: 4, background: "oklch(0.92 0.008 280)", borderRadius: 999, overflow: "hidden" }}>
          <div style={{ width: "11%", height: "100%", background: "var(--brand)" }} />
        </div>
        <div style={{ color: "var(--ink-3)", marginTop: 6, fontSize: 11 }}>
          Resets May 31.{" "}
          <span style={{ color: "var(--brand)", cursor: "pointer" }}>Manage →</span>
        </div>
      </div>

      {/* User footer */}
      <div className="row" style={{ padding: "8px 6px 0", marginTop: 8, borderTop: "1px solid var(--line)" }}>
        <div className="avatar" style={{ width: 26, height: 26, fontSize: 11, flexShrink: 0 }}>EM</div>
        <div style={{ fontSize: 12.5, lineHeight: 1.2, minWidth: 0 }}>
          <div style={{ fontWeight: 500 }}>Elena M.</div>
          <div style={{ color: "var(--ink-3)", fontSize: 11 }}>elena@orbital.dev</div>
        </div>
        <div style={{ flex: 1 }} />
        <Settings size={13} color="var(--ink-4)" strokeWidth={1.8} />
      </div>
    </aside>
  );
}
