import type { Metadata } from "next";
import { Geist, Geist_Mono, Manrope, DM_Mono } from "next/font/google";
import "./globals.css";
// Voltway storefront styling (scoped under `.vw`). Kept separate from Tailwind
// globals so the storefront look can't leak into the chat/ops components.
import "./voltway.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Storefront fonts (self-hosted by next/font). voltway.css references these via
// the CSS variables below.
const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
});

const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  weight: ["400", "500"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Voltway",
  description: "Voltway Support Desk Demo",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${manrope.variable} ${dmMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
