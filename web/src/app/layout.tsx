import type { Metadata } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";
import "./globals.css";

/** Hanken Grotesk (SIL OFL, fonts/HankenGrotesk-OFL.txt), self-hosted: no network at build or run time. */
const hanken = localFont({
  src: "./fonts/HankenGrotesk-Variable.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-hanken",
});

export const metadata: Metadata = {
  title: "PLG Super-Librarian",
  description: "Answers PLG officers' questions",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-x={hanken.variable ? "" : ""}>
      <body>{children}</body>
    </html>
  );
}
