import { useCallback, useEffect, useState } from 'react';
import type { PropertyFilterProps } from '@cloudscape-design/components/property-filter';
import {
  managers as managersApi,
  offices as officesApi,
  ticketCategories as categoriesApi,
} from '@/api';

/** Reference data sets that back an id-valued filter property. */
export type FilterOptionSource = 'manager' | 'office' | 'ticket_category';

export interface FilterOptionSpec {
  /** Backend query parameter this property maps to, e.g. `assigned_to_id`. */
  propertyKey: string;
  /** Load the option list from a reference endpoint. */
  source?: FilterOptionSource;
  /** Fixed options for enum-like fields. */
  values?: { value: string; label: string }[];
}

interface UseFilterOptionsResult {
  filteringOptions: PropertyFilterProps.FilteringOption[];
  /**
   * Turn PropertyFilter tokens into backend query params.
   *
   * Tokens for id-valued properties are dropped unless the value matches a
   * loaded option, so free text typed into the filter bar can never reach the
   * API as a malformed UUID.
   */
  tokensToParams: (tokens: readonly PropertyFilterProps.Token[]) => Record<string, unknown>;
}

/**
 * Supplies PropertyFilter with real option lists so users pick a manager or
 * category by name while the backend still receives its id.
 *
 * `specs` must be referentially stable (declare it at module scope).
 *
 * @param freeTextKey Query param that bare (property-less) tokens map to,
 *   for lists whose endpoint exposes a free-text `search`.
 */
export function useFilterOptions(
  specs: FilterOptionSpec[],
  freeTextKey?: string,
): UseFilterOptionsResult {
  const [options, setOptions] = useState<PropertyFilterProps.FilteringOption[]>([]);

  useEffect(() => {
    let cancelled = false;
    const needed = new Set(specs.map((s) => s.source).filter(Boolean));

    const load = async () => {
      const [managerRes, officeRes, categoryRes] = await Promise.all([
        needed.has('manager')
          ? managersApi.list().then((r) => r.data).catch(() => [])
          : Promise.resolve([]),
        needed.has('office')
          ? officesApi
              .list({ page_size: 1000, sort_by: 'location_name' })
              .then((r) => r.data.items)
              .catch(() => [])
          : Promise.resolve([]),
        needed.has('ticket_category')
          ? categoriesApi.list().then((r) => r.data).catch(() => [])
          : Promise.resolve([]),
      ]);
      if (cancelled) return;

      const bySource: Record<FilterOptionSource, { value: string; label: string }[]> = {
        manager: managerRes.map((m) => ({ value: m.id, label: m.name })),
        office: officeRes.map((o) => ({
          value: o.id,
          label: `#${o.office_number} ${o.location_name}`,
        })),
        ticket_category: categoryRes.map((c) => ({ value: c.id, label: c.name })),
      };

      setOptions(
        specs.flatMap((spec) => {
          const values = spec.source ? bySource[spec.source] : (spec.values ?? []);
          return values.map((v) => ({
            propertyKey: spec.propertyKey,
            value: v.value,
            label: v.label,
          }));
        }),
      );
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [specs]);

  const tokensToParams = useCallback(
    (tokens: readonly PropertyFilterProps.Token[]) => {
      const params: Record<string, unknown> = {};
      for (const token of tokens) {
        const key = token.propertyKey;
        if (token.value == null || token.value === '') continue;
        if (!key) {
          if (freeTextKey) params[freeTextKey] = token.value;
          continue;
        }
        const spec = specs.find((s) => s.propertyKey === key);
        if (spec?.source) {
          const known = options.some((o) => o.propertyKey === key && o.value === token.value);
          if (!known) continue;
        }
        params[key] = token.value;
      }
      return params;
    },
    [specs, options, freeTextKey],
  );

  return { filteringOptions: options, tokensToParams };
}

export default useFilterOptions;
