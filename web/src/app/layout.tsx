import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";
import { currentTheme } from "@/lib/server/theme";
import "./globals.css";

/** Hanken Grotesk (SIL OFL, fonts/HankenGrotesk-OFL.txt), self-hosted: no network at build or run time. */
const hanken = localFont({
  src: "./fonts/HankenGrotesk-Variable.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-hanken",
});

/** Lets the browser paint a dark canvas before the stylesheet arrives (globals.css decides the theme). */
export const viewport: Viewport = { colorScheme: "light dark" };

export const metadata: Metadata = {
  title: "PLG Super-Librarian",
  description: "Answers PLG officers' questions",
};

/** A saved Light/Dark choice is rendered on <html data-theme> (no flash); without one, CSS follows the OS. */
export default async function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={hanken.variable} data-theme={await currentTheme()}>
      <body>{children}</body>
    </html>
  );
}
