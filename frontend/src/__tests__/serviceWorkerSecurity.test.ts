import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import {
  CLEAR_API_CACHE,
  requestApiCachePurge,
} from '@/serviceWorkerRegistration';

const serviceWorkerSource = readFileSync(
  resolve(process.cwd(), 'public/sw.js'),
  'utf8',
);

describe('service worker API cache security', () => {
  it('uses a network-only API handler without Cache Storage writes', () => {
    const apiHandler = serviceWorkerSource.match(
      /async function networkOnlyApi\(request\) \{([\s\S]*?)\r?\n\}\r?\n\r?\nasync function staleWhileRevalidate/,
    )?.[1];

    expect(apiHandler).toBeDefined();
    expect(apiHandler).toContain("fetch(request, { cache: 'no-store' })");
    expect(apiHandler).toContain('status: 503');
    expect(apiHandler).not.toContain('caches.open');
    expect(apiHandler).not.toContain('cache.put');
    expect(apiHandler).not.toContain('cache.match');
    expect(serviceWorkerSource).not.toMatch(/const API_CACHE\s*=/);
  });

  it('handles migration purges for every legacy API cache', () => {
    expect(serviceWorkerSource).toContain("event.data === 'CLEAR_API_CACHE'");
    expect(serviceWorkerSource).toContain("const API_CACHE_PREFIX = 'pd-api-'");
    expect(serviceWorkerSource).toContain('name.startsWith(API_CACHE_PREFIX)');
  });

  it('posts the purge command to an active worker', async () => {
    const postMessage = vi.fn();
    const registration = {
      active: { postMessage } as unknown as ServiceWorker,
    };

    await requestApiCachePurge(registration);
    expect(postMessage).toHaveBeenCalledOnce();
    expect(postMessage).toHaveBeenCalledWith(CLEAR_API_CACHE);
  });

  it('deletes legacy API caches when no worker controls the page', async () => {
    const deleteCache = vi.fn().mockResolvedValue(true);
    const cacheStorage = {
      keys: vi.fn().mockResolvedValue(['pd-api-v1', 'pd-assets-v3']),
      delete: deleteCache,
    };
    Object.defineProperty(window, 'caches', {
      configurable: true,
      value: cacheStorage,
    });

    await requestApiCachePurge();

    expect(deleteCache).toHaveBeenCalledOnce();
    expect(deleteCache).toHaveBeenCalledWith('pd-api-v1');
  });
});