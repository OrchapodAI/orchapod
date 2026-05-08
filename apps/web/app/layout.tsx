import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Orchapod — LLM Fine-tuning Platform",
  description: "From data to deployed model in 25 minutes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full bg-slate-950 text-slate-100 antialiased flex">
        <Sidebar />
        <main className="flex-1 flex flex-col min-h-0 overflow-auto">
          {children}
        </main>
      </body>
    </html>
  );
}
