import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const apiClient = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});
const refreshClient = axios.create({ baseURL: BASE_URL, withCredentials: true });
let refreshPromise: Promise<void> | null = null;

function getCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  const value = document.cookie.split('; ').find((item) => item.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : null;
}

// Cookie-authenticated mutations use a double-submit CSRF token.
apiClient.interceptors.request.use(
  (config) => {
    const method = (config.method || 'get').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const csrfToken = getCookie('om_csrf');
      if (csrfToken) config.headers['X-CSRF-Token'] = csrfToken;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

function refreshSession(): Promise<void> {
  if (!refreshPromise) {
    refreshPromise = refreshClient.post('/auth/refresh').then(() => undefined).finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export function isPublicRoute(pathname: string): boolean {
  const publicRoots = [
    '/login',
    '/reset-password',
    '/signup',
    '/legal',
    '/verify-email',
    '/vendor-portal',
    '/client-portal',
    '/resident-portal',
    '/owner-portal',
    '/sign',
    '/lease-sign',
    '/apply',
    '/financial-verify',
    '/ack',
  ];
  return publicRoots.some((root) => pathname === root || pathname.startsWith(`${root}/`));
}

// Rotate the refresh cookie once, then retry the original request.
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config as (typeof error.config & { _sessionRetry?: boolean }) | undefined;
    const url = String(original?.url || '');
    const isAuthFlow = /\/auth\/(login|refresh|logout|mfa\/)/.test(url);
    const publicRoute = isPublicRoute(window.location.pathname);
    if (error.response?.status === 401 && original && !original._sessionRetry && !isAuthFlow && !publicRoute) {
      original._sessionRetry = true;
      try {
        await refreshSession();
        return apiClient.request(original);
      } catch {
        // Fall through to the login redirect when rotation is unavailable.
      }
    }
    if (error.response?.status === 401 && !isAuthFlow && !publicRoute) {
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;
