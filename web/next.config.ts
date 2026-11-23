import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The BFF must never leak the plg-api URL or the identity header to the browser.
  poweredByHeader: false,
  // next dev only: opening the app via 127.0.0.1 or a Codespaces forwarded port (not just localhost).
  allowedDevOrigins: ["127.0.0.1", "*.app.github.dev"],
  // The e2e tests (playwright.config.ts) run their own dev server beside a developer's: it needs its own build dir.
  ...(process.env.PLG_NEXT_DIST_DIR ? { distDir: process.env.PLG_NEXT_DIST_DIR } : {}),
  experimental: {
    agentUpgrade: "security",
  },
};

export default nextConfig;
