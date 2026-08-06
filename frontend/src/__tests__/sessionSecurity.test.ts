import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const source = (relativePath: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relativePath), 'utf8');

describe('browser token handling', () => {
  it('does not persist the primary or admin JWT in localStorage', () => {
    expect(source('src/auth/AuthContext.tsx')).not.toContain("localStorage.getItem('access_token')");
    expect(source('src/auth/AuthContext.tsx')).not.toContain("localStorage.setItem('access_token'");
    expect(source('../admin-frontend/src/context/AuthContext.tsx')).not.toContain('localStorage');
  });

  it('rotates the refresh cookie when the access cookie expires', () => {
    expect(source('src/api/client.ts')).toContain("post('/auth/refresh')");
  });

  it('scrubs portal and signing tokens from the URL', () => {
    expect(source('src/hooks/usePortalSession.ts')).toContain('replaceState');
    expect(source('src/pages/WaiverSignPage.tsx')).toContain("replaceState(null, '', '/sign')");
  });

  it('opens WebSockets without a JWT query parameter', () => {
    const wsSource = source('src/context/WSContext.tsx');
    expect(wsSource).toContain('`${WS_BASE}/ws/connect`');
    expect(wsSource).not.toContain('?token=');
  });
});