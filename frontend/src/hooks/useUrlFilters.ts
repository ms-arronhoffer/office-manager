import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { PropertyFilterProps } from '@cloudscape-design/collection-hooks';

type Token = PropertyFilterProps.Token;

/**
 * Bidirectional sync between URL query params and Cloudscape PropertyFilter tokens.
 * Enables cross-page linking (e.g., dashboard card → filtered list page).
 */
export function useUrlFilters(propertyKeys: string[]) {
  const [searchParams, setSearchParams] = useSearchParams();

  const initialTokens: Token[] = useMemo(() => {
    const tokens: Token[] = [];
    for (const [key, value] of searchParams.entries()) {
      if (propertyKeys.includes(key) || isVirtualFilter(key)) {
        tokens.push({ propertyKey: key, operator: '=', value });
      }
    }
    return tokens;
  }, []); // Only compute on mount

  const syncToUrl = useCallback(
    (tokens: Token[]) => {
      const params = new URLSearchParams();
      for (const t of tokens) {
        if (t.propertyKey && t.value) {
          const paramKey =
            t.operator && t.operator !== '=' && t.operator !== ':'
              ? `${t.propertyKey}${t.operator}`
              : t.propertyKey;
          params.set(paramKey, String(t.value));
        }
      }
      setSearchParams(params, { replace: true });
    },
    [setSearchParams],
  );

  /** Extract virtual filter values from URL (not backed by table columns). */
  const virtualFilters = useMemo(() => {
    const filters: Record<string, string> = {};
    for (const key of VIRTUAL_FILTER_KEYS) {
      const val = searchParams.get(key);
      if (val) filters[key] = val;
    }
    return filters;
  }, [searchParams]);

  const clearFilters = useCallback(() => {
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  return { initialTokens, syncToUrl, virtualFilters, clearFilters };
}

const VIRTUAL_FILTER_KEYS = [
  'expiring_soon',
  'overdue_notices',
  'due_soon',
  'expiration_year',
];

function isVirtualFilter(key: string): boolean {
  return VIRTUAL_FILTER_KEYS.includes(key);
}
