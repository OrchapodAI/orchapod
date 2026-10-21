import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { Toaster } from "@/components/Toaster";

const description = "Describe the specialist model you want in one sentence. Orchapod plans the pipeline, runs it on Nebius "
  + "with NVIDIA Nemotron, evaluates the result against its base model and shows what it cost.";

// og:image comes from app/opengraph-image.tsx. Its URL must be absolute, so the hosted build sets NEXT_PUBLIC_SITE_URL
// (https://app.<domain>) as a build arg, like NEXT_PUBLIC_API_URL.
export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: "Orchapod — LLM Fine-tuning Platform",
  description,
  openGraph: { title: "Orchapod.ai", description, siteName: "Orchapod.ai", type: "website" },
  twitter: { card: "summary_large_image", title: "Orchapod.ai", description },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" style={{ height: '100%' }}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body style={{ height: '100%', display: 'grid', gridTemplateColumns: '248px 1fr', margin: 0 }}>
        <Sidebar />
        <main style={{ display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'auto' }}>
          {children}
        </main>
        <Toaster />
      </body>
    </html>
  );
}
