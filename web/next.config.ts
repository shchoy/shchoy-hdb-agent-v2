import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The BFF must never leak the plg-api URL or the identity header to the browser.
  poweredByHeader: false,
};

export default nextConfig;
