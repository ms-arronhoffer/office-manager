import { useEffect, useState } from 'react';
import { attachments as attachmentsApi } from '@/api';

/**
 * Fetch attachment counts for a batch of entities of one type.
 * Returns a map keyed by entity id (string) -> count.
 *
 * Usage:
 *   const counts = useAttachmentCounts('vendor', items.map(v => v.id));
 *   ...cell: (item) => counts[item.id] ?? 0
 */
export function useAttachmentCounts(
  entityType: string,
  ids: (string | undefined | null)[],
): Record<string, number> {
  const [counts, setCounts] = useState<Record<string, number>>({});

  // Stable key for dependency comparison: we only refetch when the set changes.
  const idKey = ids.filter(Boolean).sort().join(',');

  useEffect(() => {
    if (!idKey) {
      setCounts({});
      return;
    }
    let cancelled = false;
    const cleanIds = idKey.split(',');
    attachmentsApi
      .getCounts(entityType, cleanIds)
      .then((res) => {
        if (!cancelled) setCounts(res.data);
      })
      .catch(() => {
        // Non-fatal: column will fall back to 0 / unknown.
        if (!cancelled) setCounts({});
      });
    return () => {
      cancelled = true;
    };
  }, [entityType, idKey]);

  return counts;
}
