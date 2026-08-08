import { useEffect, useMemo, useState } from 'react';

/**
 * Client-side paging for portal tables.
 *
 * Portal accounts can own hundreds of leases, work orders and documents.
 * Rendering every row at once is what makes the portals feel slow on the large
 * portfolios that matter most, so tables page through a bounded slice instead.
 * The backend serves these collections in bounded pages too; this keeps the
 * rendered DOM small for whatever arrives.
 */
export const DEFAULT_PORTAL_PAGE_SIZE = 25;

export interface PagedItems<T> {
  pageItems: T[];
  currentPageIndex: number;
  pagesCount: number;
  setCurrentPageIndex: (index: number) => void;
  /** True once paging is actually doing something, so the UI can hide it. */
  isPaginated: boolean;
  totalCount: number;
}

export function usePagedItems<T>(
  items: T[],
  pageSize: number = DEFAULT_PORTAL_PAGE_SIZE,
): PagedItems<T> {
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const pagesCount = Math.max(1, Math.ceil(items.length / pageSize));

  // Keep the selection valid when the underlying collection shrinks (a filter
  // change or a refresh) so the table cannot land on an empty page.
  useEffect(() => {
    if (currentPageIndex > pagesCount) setCurrentPageIndex(pagesCount);
  }, [currentPageIndex, pagesCount]);

  const pageItems = useMemo(() => {
    const start = (currentPageIndex - 1) * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, currentPageIndex, pageSize]);

  return {
    pageItems,
    currentPageIndex,
    pagesCount,
    setCurrentPageIndex,
    isPaginated: items.length > pageSize,
    totalCount: items.length,
  };
}
