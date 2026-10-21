import type { ReactNode } from "react";

export function Callout({ tone, title, children }: { tone: "amber" | "rose"; title: string; children: ReactNode }) {
  return (
    <div style={{
      background: `var(--${tone}-soft)`, border: `1px solid var(--${tone})`, borderRadius: 6,
      padding: "10px 14px", color: `var(--${tone}-ink)`, fontSize: 13, lineHeight: 1.5,
    }}>
      <div style={{ fontWeight: 600 }}>{title}</div>
      <div style={{ marginTop: 2 }}>{children}</div>
    </div>
  );
}
