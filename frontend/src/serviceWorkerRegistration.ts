/**
 * Service worker registration (Phase 1.6 PWA).
 *
 * Registered only in production builds — in dev, Vite serves modules that the
 * SW's caching would interfere with. Safe to call unconditionally; it no-ops
 * when the browser lacks service-worker support or when not on https/localhost.
 */
export function registerServiceWorker(): void {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;
  // Vite injects import.meta.env.PROD; guard defensively for test/build tooling.
  const isProd = (import.meta as unknown as { env?: { PROD?: boolean } }).env?.PROD;
  if (!isProd) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* registration failures are non-fatal; app still works online */
    });
  });
}
