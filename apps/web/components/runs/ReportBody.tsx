import { Fragment } from "react";
import { BASE } from "@/lib/api";
import { reportBlocks, splitReport, type ReportLine } from "@/lib/runEvents";

const line = (parts: ReportLine) => parts.map((p, i) => typeof p === "string" ? p : (
  <a key={i} href={p.href} target="_blank" rel="noreferrer" style={{ color: "var(--brand)", textDecoration: "underline", wordBreak: "break-all" }}>{p.text}</a>
));

/** The Agent's report: its title, then what the reporter writes (headings, lines, bullets, artifact links; see reportBlocks). Text nodes only. */
export function ReportBody({ markdown }: { markdown: string }) {
  const { title, body } = splitReport(markdown);
  return (
    <div className="col" style={{ gap: 10, fontSize: 13, lineHeight: 1.6 }}>
      {title && <h2 style={{ fontSize: 15, fontWeight: 600 }}>{title}</h2>}
      {reportBlocks(body, BASE).map((b, i) => b.type === "h"
        ? <h3 key={i} style={{ fontSize: 13.5, fontWeight: 600, margin: "6px 0 0" }}>{b.text}</h3>
        : b.type === "ul"
          ? <ul key={i} style={{ margin: 0, paddingLeft: 18 }}>{b.lines.map((l, j) => <li key={j}>{line(l)}</li>)}</ul>
          : <p key={i} style={{ margin: 0 }}>{b.lines.map((l, j) => <Fragment key={j}>{j > 0 && <br />}{line(l)}</Fragment>)}</p>)}
    </div>
  );
}
