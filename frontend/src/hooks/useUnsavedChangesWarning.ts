import { useEffect } from 'react';

/**
 * Warns the user before navigating away from the page when `dirty` is true.
 *
 * This hook attaches a `beforeunload` listener so the browser shows its
 * native "are you sure you want to leave?" prompt for full reloads, tab
 * closes, and external navigation.
 *
 * Note: in-app navigation (clicking a React Router <Link>) is not blocked
 * by `beforeunload`. To block in-app navigation cleanly, the app would
 * need to migrate to a data router (createBrowserRouter) and use
 * `useBlocker`. Until then, prompt the user manually before navigating
 * away from a dirty form (e.g. on Cancel buttons).
 */
export function useUnsavedChangesWarning(dirty: boolean, message?: string) {
  const text = message ?? 'You have unsaved changes. Are you sure you want to leave?';

  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Modern browsers ignore the message text but require returnValue to be set.
      e.returnValue = text;
      return text;
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty, text]);
}
