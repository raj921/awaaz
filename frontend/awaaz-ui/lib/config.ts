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
 * Absolute WebSocket URL for the gateway.
 *
 * Derived from API_URL so http→ws and https→wss always match; a hard-coded
 * scheme breaks the moment the app is served over TLS, because browsers
 * refuse a ws:// connection from an https:// page. With a same-origin API
 * base the page's own location supplies the host.
 */
export function wsURL(path: string, params?: Record<string, string>): string {
  const base =
    API_URL ||
    (typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");
  const url = new URL(base);
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
