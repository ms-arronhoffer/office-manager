import { useEffect, useRef } from 'react';

function isInputFocused(): boolean {
  const el = document.activeElement;
  return (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement ||
    el?.getAttribute('contenteditable') === 'true'
  );
}

/**
 * "Go to" sequences: press `g` then the listed key. Keeps single keys free for
 * page-local use and avoids clashing with browser or screen-reader chords.
 */
export const GO_TO_ROUTES: Record<string, { path: string; label: string }> = {
  d: { path: '/', label: 'Dashboard' },
  o: { path: '/offices', label: 'Offices' },
  l: { path: '/leases', label: 'Leases' },
  t: { path: '/maintenance-tickets', label: 'Maintenance tickets' },
  v: { path: '/vendors', label: 'Vendors' },
  n: { path: '/landlords', label: 'Landlords' },
  r: { path: '/residential', label: 'Residential' },
  m: { path: '/maintenance', label: 'Maintenance' },
  f: { path: '/finance', label: 'Finance' },
  s: { path: '/settings', label: 'Settings' },
  h: { path: '/help', label: 'Help' },
};

/** How long after pressing `g` the follow-up key is still accepted. */
const SEQUENCE_TIMEOUT_MS = 1500;

export function useKeyboardShortcuts(
  onShowShortcuts: () => void,
  onToggleAssistant?: () => void,
  onNavigate?: (path: string) => void,
) {
  // Timestamp of the last bare `g` press, used to detect "g then key".
  const goPressedAt = useRef(0);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ctrl+K / Cmd+K: focus global search
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector<HTMLInputElement>(
          '[data-testid="global-search"] input, [placeholder*="Search"] input, input[type="search"]'
        );
        if (searchInput) {
          searchInput.focus();
        } else {
          // Fallback: try Cloudscape search slot input
          const csInput = document.querySelector<HTMLInputElement>('.awsui_search input');
          csInput?.focus();
        }
        return;
      }

      // Ctrl+J / Cmd+J: toggle the AI portfolio assistant drawer
      if ((e.ctrlKey || e.metaKey) && e.key === 'j') {
        e.preventDefault();
        onToggleAssistant?.();
        return;
      }

      // Everything below is a bare key, so ignore it while typing or when a
      // modifier is held (those belong to the browser or the OS).
      if (e.ctrlKey || e.metaKey || e.altKey || isInputFocused()) return;

      // ? key: show shortcuts help
      if (e.key === '?') {
        e.preventDefault();
        onShowShortcuts();
        return;
      }

      // Second half of a "g then key" navigation sequence.
      if (goPressedAt.current && Date.now() - goPressedAt.current < SEQUENCE_TIMEOUT_MS) {
        goPressedAt.current = 0;
        const target = GO_TO_ROUTES[e.key.toLowerCase()];
        if (target && onNavigate) {
          e.preventDefault();
          onNavigate(target.path);
        }
        return;
      }

      if (e.key === 'g') {
        goPressedAt.current = Date.now();
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onShowShortcuts, onToggleAssistant, onNavigate]);
}
