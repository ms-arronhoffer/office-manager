import { useEffect, useState } from 'react';
import client from '@/api/client';

interface EntitlementsState {
  features: Record<string, boolean>;
  plan: string | null;
  loading: boolean;
}

/**
 * Fetches the current organization's effective entitlements so the UI can show,
 * hide, or lock plan-gated features. Mirrors the backend
 * ``GET /organizations/me/entitlements`` ``features`` map (single source of
 * truth in ``entitlements.py``).
 */
export function useEntitlements() {
  const [state, setState] = useState<EntitlementsState>({
    features: {},
    plan: null,
    loading: true,
  });

  useEffect(() => {
    let active = true;
    client
      .get<{ features: Record<string, boolean>; plan: string }>('/organizations/me/entitlements')
      .then((res) => {
        if (!active) return;
        setState({ features: res.data.features || {}, plan: res.data.plan ?? null, loading: false });
      })
      .catch(() => {
        if (!active) return;
        setState({ features: {}, plan: null, loading: false });
      });
    return () => {
      active = false;
    };
  }, []);

  const hasFeature = (key: string) => Boolean(state.features[key]);

  return { ...state, hasFeature };
}

export default useEntitlements;
