import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

export interface PortalFlash {
  type: 'success' | 'error';
  content: string;
}

interface Options {
  /** Persistent portal path, e.g. `/resident-portal`. */
  portalPath: string;
  /** Redeems a single-use signup token for a persistent portal token. */
  signup?: (signupToken: string) => Promise<{ data: { portal_token: string } }>;
  /** Loads the portal's data. Throws so the hook can classify auth failures. */
  load: (activeToken: string) => Promise<void>;
}

export interface PortalSession {
  token: string;
  loading: boolean;
  authError: boolean;
  flash: PortalFlash | null;
  setFlash: (flash: PortalFlash | null) => void;
  /** Re-runs the portal's data load against the active token. */
  reload: () => Promise<void>;
}

const statusOf = (err: unknown): number | undefined =>
  (err as { response?: { status?: number } })?.response?.status;

/**
 * Shared token lifecycle for the external portals (resident, owner, client,
 * vendor). Each portal previously reimplemented the same signup redemption,
 * token handoff and 401 handling; centralising it keeps their access behaviour
 * identical and fixes it in one place.
 *
 * The single-use invite lands on `<portalPath>/signup?token=...` and is
 * exchanged for the persistent `<portalPath>?token=...` link.
 */
export function usePortalSession({ portalPath, signup, load }: Options): PortalSession {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();

  const isSignupRoute = location.pathname.endsWith('/signup');
  const urlToken = searchParams.get('token') ?? '';
  const signupToken = isSignupRoute ? urlToken : '';
  const tokenParam = isSignupRoute ? '' : urlToken;

  const [token, setToken] = useState(tokenParam);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);
  const [flash, setFlash] = useState<PortalFlash | null>(null);

  // Held in a ref so a caller's inline `load` cannot restart the session.
  const loadRef = useRef(load);
  loadRef.current = load;

  const runLoad = useCallback(async (activeToken: string) => {
    try {
      await loadRef.current(activeToken);
    } catch (err: unknown) {
      if (statusOf(err) === 401) {
        setAuthError(true);
      } else {
        setFlash({ type: 'error', content: 'Failed to load portal data.' });
      }
    }
  }, []);

  const redeemSignup = useCallback(async (): Promise<string> => {
    if (!signup) return '';
    try {
      const res = await signup(signupToken);
      const newToken = res.data.portal_token;
      setToken(newToken);
      navigate(`${portalPath}?token=${newToken}`, { replace: true });
      return newToken;
    } catch (err: unknown) {
      // Portals report an exhausted invite as either 400 or 410.
      const status = statusOf(err);
      if (status === 400 || status === 410) {
        setFlash({
          type: 'error',
          content: 'This signup link has expired. Please request a new one.',
        });
      }
      setAuthError(true);
      return '';
    }
  }, [signup, signupToken, navigate, portalPath]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      let activeToken = tokenParam;
      if (signupToken) {
        activeToken = await redeemSignup();
      }
      if (!activeToken) {
        setAuthError(true);
        setLoading(false);
        return;
      }
      await runLoad(activeToken);
      setLoading(false);
    })();
    // Runs once per mount, mirroring the original per-portal behaviour.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reload = useCallback(async () => {
    if (!token) return;
    await runLoad(token);
  }, [token, runLoad]);

  return { token, loading, authError, flash, setFlash, reload };
}

export default usePortalSession;
