import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FinRisk Sentinel",
  description: "Portfolio intelligence with evidence in view.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <script src="/app-bootstrap.js" defer />
      </head>
      <body>{children}</body>
    </html>
  );
}
