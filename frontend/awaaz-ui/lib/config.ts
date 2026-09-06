/**
 * Runtime configuration for the browser client.
 *
 * The API base is resolved once, here, instead of being re-derived with a
 * `?? "http://localhost:18080"` fallback in every file that needs it — those
 * copies drifted (the Go gateway defaults to :8080, the UI assumed :18080),
 * which is exactly the kind of mismatch that makes a socket "connect" to
 * nothing.
 *
 * The default is the empty string: same-origin. Requests then go to
 * `/api/v1/...` on whatever host is serving the page and Next proxies them to
 * the gateway (see `next.config.ts`). An absolute default cannot work when the
 * page is served from anywhere but the developer's own machine — a phone on
 * the LAN, a preview URL or a deployed origin would all resolve `localhost`
 * to themselves. Set NEXT_PUBLIC_API_URL to target a gateway directly.
 */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(
  /\/+$/,
  "",
);

/**
 * Gateway origin for the voice WebSocket.
 *
 * The socket connects DIRECTLY here, bypassing the Next rewrite proxy:
 * rewrites only forward plain HTTP, so a ws:// upgrade sent same-origin
 * dies inside the Next server and the room fails with a bare onerror
 * ("voice session connection failed"). NEXT_PUBLIC_API_URL (same-origin
 * fetch) is untouched by this.
 *
 * Default is the local dev gateway. Production MUST set
 * NEXT_PUBLIC_GATEWAY_URL to the backend origin (wss follows https
 * automatically), otherwise the socket resolves to the page host.
 */
export const GATEWAY_URL = (
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:18080"
).replace(/\/+$/, "");

/**
 * Absolute WebSocket URL for the gateway.
 *
 * Derived from GATEWAY_URL so http→ws and https→wss always match; a
 * hard-coded scheme breaks the moment the app is served over TLS, because
 * browsers refuse a ws:// connection from an https:// page.
 */
export function wsURL(path: string, params?: Record<string, string>): string {
  const url = new URL(GATEWAY_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path;
  url.search = params ? new URLSearchParams(params).toString() : "";
  return url.toString();
}

/** Audio format the voice room expects: raw PCM16LE mono at 16 kHz. */
export const AUDIO = {
  sampleRate: 16000,
  frameSize: 4096,
} as const;
