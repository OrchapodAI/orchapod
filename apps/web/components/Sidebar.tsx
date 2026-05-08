"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { GitBranch, LayoutDashboard, Play, Box } from "lucide-react";
import clsx from "clsx";

const NAV = [
  { href: "/workflows", label: "Workflows", icon: LayoutDashboard },
  { href: "/runs",      label: "Runs",      icon: Play },
  { href: "/registry",  label: "Registry",  icon: Box },
];

export function Sidebar() {
  const path = usePathname();

  return (
    <aside className="w-[220px] shrink-0 flex flex-col bg-slate-900 border-r border-slate-800 h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
            <GitBranch className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-sm tracking-tight text-slate-100">
            orchapod
          </span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
                active
                  ? "bg-violet-600/20 text-violet-300 font-medium"
                  : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
              )}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-slate-800">
        <p className="text-xs text-slate-600">v0.1.0 · open source</p>
      </div>
    </aside>
  );
}
