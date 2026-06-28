import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Autosuggest from '@cloudscape-design/components/autosuggest';
import { search } from '@/api';
import type { SearchResult } from '@/types';

const ENTITY_ROUTES: Record<string, string> = {
  office: '/offices',
  lease: '/leases',
  maintenance_ticket: '/maintenance-tickets',
  landlord: '/landlords',
  vendor: '/vendors',
  transition: '/transitions',
  hvac_contract: '/hvac-contracts',
  management_company: '/management-companies',
  waiver: '/waivers',
};

const GlobalSearchBar: React.FC = () => {
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const [options, setOptions] = useState<{ value: string; label: string; description: string; tags?: string[] }[]>([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const resultsRef = useRef<SearchResult[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleChange = useCallback(
    (detail: { value: string }) => {
      const q = detail.value;
      setValue(q);

      if (debounceRef.current) clearTimeout(debounceRef.current);

      if (q.length < 2) {
        setOptions([]);
        return;
      }

      debounceRef.current = setTimeout(async () => {
        setLoading(true);
        try {
          const res = await search.query(q);
          resultsRef.current = res.data;
          setOptions(
            res.data.map((r) => ({
              value: `${r.entity_type}:${r.entity_id}`,
              label: r.label,
              description: r.sublabel,
              tags: [r.entity_type.replace('_', ' ')],
            })),
          );
        } catch {
          setOptions([]);
        } finally {
          setLoading(false);
        }
      }, 300);
    },
    [],
  );

  const handleSelect = useCallback(
    (detail: { value: string }) => {
      const [entityType, entityId] = detail.value.split(':');
      // Phase (b): prefer the server-provided deep-link route when present.
      const match = resultsRef.current.find(
        (r) => `${r.entity_type}:${r.entity_id}` === detail.value,
      );
      const target =
        match?.route ||
        (ENTITY_ROUTES[entityType] && entityId
          ? `${ENTITY_ROUTES[entityType]}/${entityId}`
          : '');
      if (target) {
        navigate(target);
        setValue('');
        setOptions([]);
      }
    },
    [navigate],
  );

  // Cmd-K / Ctrl-K focuses the search box (skip when an editable element is focused, except the search itself).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const isShortcut = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
      if (!isShortcut) return;
      e.preventDefault();
      const input = containerRef.current?.querySelector<HTMLInputElement>('input');
      if (input) input.focus();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <div ref={containerRef} style={{ minWidth: 320 }}>
      <Autosuggest
        value={value}
        onChange={({ detail }) => handleChange(detail)}
        onSelect={({ detail }) => handleSelect(detail)}
        options={options}
        loadingText="Searching..."
        statusType={loading ? 'loading' : 'finished'}
        placeholder="Search anything (Ctrl+K)..."
        ariaLabel="Global search"
        empty="No results found"
        enteredTextLabel={(v) => `Search for "${v}"`}
      />
    </div>
  );
};

export default GlobalSearchBar;
