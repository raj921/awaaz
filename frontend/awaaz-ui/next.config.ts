import type { NextConfig } from "next";

/**
 * The gateway is a separate Go service. Proxying `/api/*` (and the voice
 * WebSocket, which upgrades over the same path) keeps the browser on a single
 * origin: no CORS preflights, no cross-origin WebSocket, and no absolute
 * `localhost` URL baked into the client bundle that breaks on every host
 * except the developer's own machine.
 */
const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://127.0.0.1:18080";

const nextConfig: NextConfig = {
  async rewrites() {
    // Skip the proxy when the client is pointed at a gateway directly.
    if (process.env.NEXT_PUBLIC_API_URL) return [];
    return [
      { source: "/api/:path*", destination: `${GATEWAY_URL}/api/:path*` },
      { source: "/healthz", destination: `${GATEWAY_URL}/healthz` },
    ];
  },
};

export default nextConfig;
