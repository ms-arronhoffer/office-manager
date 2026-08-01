import { useEffect, useId } from 'react';
import { useUnsavedChanges } from '@/context/UnsavedChangesContext';

/**
 * Warns before abandoning a form with pending edits.
 *
 * Covers both exits: `beforeunload` handles reloads, tab closes and external
 * navigation, while registering with {@link useUnsavedChanges} lets in-app
 * navigation (sidebar, logo, breadcrumbs) prompt as well.
 */
export function useUnsavedChangesWarning(dirty: boolean, message?: string) {
  const text = message ?? 'You have unsaved changes. Are you sure you want to leave?';
  const key = useId();
  const { setDirty } = useUnsavedChanges();

  useEffect(() => {
    setDirty(key, dirty);
    return () => setDirty(key, false);
  }, [dirty, key, setDirty]);

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

export default useUnsavedChangesWarning;
