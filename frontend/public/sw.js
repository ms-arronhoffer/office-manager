/*
 * Portfolio Desk service worker (Phase 1.6 PWA).
 *
 * Hand-rolled (no build plugin) so it works with Vite's hashed asset output:
 *   - App shell / navigations: network-first, fall back to cached index.html so
 *     the SPA still boots offline.
 *   - Built static assets (/assets/*, icons, manifest): stale-while-revalidate.
 *   - API GETs: network-only. Authenticated data is never persisted in Cache
 *     Storage and returns an explicit JSON 503 response while offline.
 *     Mutations (POST/PATCH/PUT/DELETE) always hit the network.
 *
 * Bump CACHE_VERSION to invalidate old caches on deploy.
 */
const CACHE_VERSION = 'v3';
const SHELL_CACHE = `pd-shell-${CACHE_VERSION}`;
const ASSET_CACHE = `pd-assets-${CACHE_VERSION}`;
const API_CACHE_PREFIX = 'pd-api-';

const SHELL_URLS = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  const keep = new Set([SHELL_CACHE, ASSET_CACHE]);
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith(API_CACHE_PREFIX) || !keep.has(name))
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
  if (event.data === 'CLEAR_API_CACHE') event.waitUntil(clearApiCaches());
});

async function clearApiCaches() {
  const names = await caches.keys();
  await Promise.all(
    names
      .filter((name) => name.startsWith(API_CACHE_PREFIX))
      .map((name) => caches.delete(name)),
  );
}

function isApiRequest(url) {
  return url.pathname.startsWith('/api/');
}

function isAsset(url) {
  return (
    url.pathname.startsWith('/assets/') ||
    url.pathname.startsWith('/icons/') ||
    url.pathname === '/manifest.webmanifest'
  );
}

async function networkOnlyApi(request) {
  try {
    return await fetch(request, { cache: 'no-store' });
  } catch (err) {
    return new Response(
      JSON.stringify({ detail: 'Offline: authenticated data requires a network connection.' }),
      {
        status: 503,
        headers: {
          'Cache-Control': 'no-store',
          'Content-Type': 'application/json',
        },
      },
    );
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(ASSET_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => cached);
  return cached || network;
}

async function navigationHandler(request) {
  try {
    const response = await fetch(request);
    const cache = await caches.open(SHELL_CACHE);
    cache.put('/index.html', response.clone());
    return response;
  } catch (err) {
    const cache = await caches.open(SHELL_CACHE);
    const cached = (await cache.match('/index.html')) || (await cache.match('/'));
    if (cached) return cached;
    return new Response('You are offline.', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return; // never intercept mutations

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // let cross-origin pass through

  if (request.mode === 'navigate') {
    event.respondWith(navigationHandler(request));
    return;
  }
  if (isApiRequest(url)) {
    event.respondWith(networkOnlyApi(request));
    return;
  }
  if (isAsset(url)) {
    event.respondWith(staleWhileRevalidate(request));
  }
});
