import React, { createContext, useCallback, useContext, useRef } from 'react';

interface UnsavedChangesValue {
  /** Called by forms to publish their current dirty state. */
  setDirty: (key: string, dirty: boolean) => void;
  /** True when any registered form has unsaved edits. */
  isDirty: () => boolean;
  /**
   * Returns true when it is safe to navigate. Prompts when edits are pending
   * and clears the guard once the user accepts, so the destination page does
   * not re-prompt.
   */
  confirmLeave: () => boolean;
}

const UnsavedChangesContext = createContext<UnsavedChangesValue | null>(null);

const MESSAGE = 'You have unsaved changes. Leave this page and discard them?';

/**
 * Tracks unsaved form state app-wide so shared navigation (sidebar, logo,
 * breadcrumbs) can prompt before discarding edits. `BrowserRouter` has no
 * `useBlocker`, so navigation sources opt in by calling `confirmLeave`.
 */
export const UnsavedChangesProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const dirtyKeys = useRef<Set<string>>(new Set());

  const setDirty = useCallback((key: string, dirty: boolean) => {
    if (dirty) dirtyKeys.current.add(key);
    else dirtyKeys.current.delete(key);
  }, []);

  const isDirty = useCallback(() => dirtyKeys.current.size > 0, []);

  const confirmLeave = useCallback(() => {
    if (dirtyKeys.current.size === 0) return true;
    // eslint-disable-next-line no-alert
    const ok = window.confirm(MESSAGE);
    if (ok) dirtyKeys.current.clear();
    return ok;
  }, []);

  return (
    <UnsavedChangesContext.Provider value={{ setDirty, isDirty, confirmLeave }}>
      {children}
    </UnsavedChangesContext.Provider>
  );
};

export function useUnsavedChanges(): UnsavedChangesValue {
  return (
    useContext(UnsavedChangesContext) ?? {
      setDirty: () => undefined,
      isDirty: () => false,
      confirmLeave: () => true,
    }
  );
}

export default UnsavedChangesContext;
