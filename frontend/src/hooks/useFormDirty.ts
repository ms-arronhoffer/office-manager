import { useCallback, useEffect, useMemo, useRef } from 'react';

/**
 * Reports whether a form's state has diverged from the values it started with.
 *
 * `ready` should become true once an edit form has loaded its record, so the
 * baseline is the saved record rather than the empty initial state.
 */
export function useFormDirty<T>(value: T, ready = true) {
  const baseline = useRef<string | null>(null);
  const serialized = useMemo(() => JSON.stringify(value ?? null), [value]);

  useEffect(() => {
    if (ready && baseline.current === null) {
      baseline.current = serialized;
    }
  }, [ready, serialized]);

  const markClean = useCallback(() => {
    baseline.current = serialized;
  }, [serialized]);

  const dirty = ready && baseline.current !== null && baseline.current !== serialized;

  return { dirty, markClean };
}

export default useFormDirty;
