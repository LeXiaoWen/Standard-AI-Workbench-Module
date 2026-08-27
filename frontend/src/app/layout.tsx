import type { Metadata } from "next";
import "github-markdown-css/github-markdown-light.css";
import "highlight.js/styles/github.css";
import "./globals.css";
import { AppProviders } from "./providers";

export const metadata: Metadata = {
  title: "AI Workbench",
  description: "Reusable OpenAI-compatible streaming chat workbench",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body><AppProviders>{children}</AppProviders></body>
    </html>
  );
}
