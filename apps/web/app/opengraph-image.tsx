import { ImageResponse } from "next/og";

export const alt = "Orchapod.ai: describe the specialist model you want in one sentence";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// The social card (og:image; X falls back to it). Rendered at build time with next/og's bundled font: no network needed.
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div style={{
        width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", padding: 80,
        background: "linear-gradient(135deg, #241a5c 0%, #4a37b0 65%, #7fbf3f 140%)", color: "white",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <div style={{
            width: 104, height: 104, borderRadius: 26, background: "rgba(255,255,255,0.16)", border: "2px solid rgba(255,255,255,0.3)",
            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 48,
          }}>op</div>
          <div style={{ fontSize: 80, letterSpacing: -2 }}>Orchapod.ai</div>
        </div>
        <div style={{ fontSize: 40, marginTop: 48, lineHeight: 1.25 }}>Describe the specialist model you want in one sentence.</div>
        <div style={{ fontSize: 30, marginTop: 28, lineHeight: 1.4, opacity: 0.85 }}>
          Orchapod plans the pipeline, runs it on Nebius with NVIDIA Nemotron, evaluates it against its base model and shows what it cost.
        </div>
      </div>
    ),
    size,
  );
}
