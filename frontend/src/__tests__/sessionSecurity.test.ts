import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { isPublicRoute } from '@/api/client';

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

  it('does not refresh or redirect an unauthenticated login page', () => {
    const clientSource = source('src/api/client.ts');
    expect(clientSource).toContain('isPublicRoute');
    expect(clientSource).toContain('!publicRoute');
    expect(source('../admin-frontend/src/api/index.ts')).toContain('isPublicAuthPage');
  });

  it.each([
    '/financial-verify/3xvTdCpmoY20ilvmJDUFZOa3Jlc79Kylfa89_ow7H80',
    '/financial-verify',
    '/apply/application-token',
    '/sign/waiver-token',
    '/resident-portal',
  ])('does not redirect public route %s to login', (pathname) => {
    expect(isPublicRoute(pathname)).toBe(true);
  });

  it('keeps authenticated application routes protected', () => {
    expect(isPublicRoute('/residential/applications')).toBe(false);
    expect(isPublicRoute('/finance/connections')).toBe(false);
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

  it('does not start authenticated background calls on public routes', () => {
    expect(source('src/context/WSContext.tsx')).toContain('if (!isAuthenticated) return');
    expect(source('src/context/SiteSettingsContext.tsx')).toContain(
      'if (!isPublicRoute(window.location.pathname)) load()',
    );
  });
});