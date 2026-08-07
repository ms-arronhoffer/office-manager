/**
 * Service worker registration (Phase 1.6 PWA).
 *
 * Registered only in production builds — in dev, Vite serves modules that the
 * SW's caching would interfere with. Safe to call unconditionally; it no-ops
 * when the browser lacks service-worker support or when not on https/localhost.
 */
export const CLEAR_API_CACHE = 'CLEAR_API_CACHE';
const API_CACHE_PREFIX = 'pd-api-';

type ActiveServiceWorkerRegistration = Pick<ServiceWorkerRegistration, 'active'>;

export async function requestApiCachePurge(
  registration?: ActiveServiceWorkerRegistration,
): Promise<void> {
  const controller =
    typeof navigator !== 'undefined' && 'serviceWorker' in navigator
      ? navigator.serviceWorker.controller
      : null;
  const worker = registration?.active ?? controller;
  worker?.postMessage(CLEAR_API_CACHE);

  if (typeof window === 'undefined' || !('caches' in window)) return;
  try {
    const names = await window.caches.keys();
    await Promise.all(
      names
        .filter((name) => name.startsWith(API_CACHE_PREFIX))
        .map((name) => window.caches.delete(name)),
    );
  } catch {
    /* cache cleanup is best-effort for browsers with partial PWA support */
  }
}

export function registerServiceWorker(): void {
  if (typeof window === 'undefined') return;
  if (!('serviceWorker' in navigator)) return;
  // Vite injects import.meta.env.PROD; guard defensively for test/build tooling.
  const isProd = (import.meta as unknown as { env?: { PROD?: boolean } }).env?.PROD;
  if (!isProd) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then(() => navigator.serviceWorker.ready)
      .then((registration) => requestApiCachePurge(registration))
      .catch(() => {
        /* registration failures are non-fatal; app still works online */
      });
  });
}
