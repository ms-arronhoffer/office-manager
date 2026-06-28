import { useEffect } from 'react';

function isInputFocused(): boolean {
  const el = document.activeElement;
  return (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el?.getAttribute('contenteditable') === 'true'
  );
}

export function useKeyboardShortcuts(
  onShowShortcuts: () => void,
  onToggleAssistant?: () => void,
) {
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
      }

      // Ctrl+J / Cmd+J: toggle the AI portfolio assistant drawer
      if ((e.ctrlKey || e.metaKey) && e.key === 'j') {
        e.preventDefault();
        onToggleAssistant?.();
      }

      // ? key: show shortcuts help (only when not typing in an input)
      if (e.key === '?' && !isInputFocused()) {
        e.preventDefault();
        onShowShortcuts();
      }
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onShowShortcuts, onToggleAssistant]);
}
