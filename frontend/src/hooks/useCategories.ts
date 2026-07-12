import { useCallback, useEffect, useState } from 'react';
import client from '@/api/client';
import type { CategoriesState, PrimaryCategory } from '@/types';

interface CategoriesHookState {
  catalog: PrimaryCategory[];
  labels: Record<string, string>;
  enabledCategories: PrimaryCategory[];
  overrides: Record<string, boolean>;
  effective: PrimaryCategory[];
  loading: boolean;
}

const EMPTY: CategoriesHookState = {
  catalog: [],
  labels: {},
  enabledCategories: [],
  overrides: {},
  effective: [],
  loading: true,
};

// If the config can't be loaded (e.g. transient error, or a user without an
// organization), fall back to the historical always-on categories so the app's
// primary surfaces never disappear. Mirrors backend DEFAULT_ENABLED_CATEGORIES.
const FALLBACK: CategoriesHookState = {
  catalog: ['commercial', 'residential', 'self_storage'],
  labels: {
    commercial: 'Commercial',
    residential: 'Residential',
    self_storage: 'Self Storage',
  },
  enabledCategories: ['commercial', 'residential'],
  overrides: {},
  effective: ['commercial', 'residential'],
  loading: false,
};

/**
 * Fetches the current organization's primary-category configuration so the UI
 * can show or hide category-scoped surfaces (Commercial / Residential / Self
 * Storage). Mirrors the backend ``GET /organizations/me/categories`` response
 * (single source of truth in ``categories.py``).
 *
 * ``isEnabled`` reports against the *effective* set (org-managed enabled list
 * with platform overrides applied), matching the backend runtime guard.
 */
export function useCategories() {
  const [state, setState] = useState<CategoriesHookState>(EMPTY);

  const load = useCallback(() => {
    let active = true;
    setState((s) => ({ ...s, loading: true }));
    client
      .get<CategoriesState>('/organizations/me/categories')
      .then((res) => {
        if (!active) return;
        const data = res.data;
        setState({
          catalog: data.catalog || [],
          labels: data.labels || {},
          enabledCategories: data.enabled_categories || [],
          overrides: data.overrides || {},
          effective: data.effective || [],
          loading: false,
        });
      })
      .catch(() => {
        if (!active) return;
        setState(FALLBACK);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => load(), [load]);

  const isEnabled = useCallback(
    (category: PrimaryCategory) => state.effective.includes(category),
    [state.effective],
  );

  return { ...state, isEnabled, reload: load };
}

export default useCategories;
