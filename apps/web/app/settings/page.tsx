"use client";
export default function SettingsPage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="op-topbar">
        <div className="op-crumbs"><span className="here">Settings</span></div>
        <div className="spacer" />
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", padding: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.02em" }}>Settings</h1>
        <p className="muted" style={{ fontSize: 13.5, marginTop: 4 }}>Coming soon</p>
      </div>
    </div>
  );
}
