import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Orchapod — LLM Fine-tuning Platform",
  description: "From data to deployed model in 25 minutes.",
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
      </body>
    </html>
  );
}
