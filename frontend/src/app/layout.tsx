import type { Metadata } from "next";
import "github-markdown-css/github-markdown-light.css";
import "highlight.js/styles/github.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Workbench",
  description: "Reusable OpenAI-compatible streaming chat workbench",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
