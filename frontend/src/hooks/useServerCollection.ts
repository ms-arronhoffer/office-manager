import { useState, useEffect, useCallback, useRef } from 'react';
import type { TableProps, PaginationProps } from '@cloudscape-design/components';
import { usePreferences } from '@/context/PreferencesContext';
import type { PaginatedResponse } from '@/types';

interface UseServerCollectionOptions<T> {
  fetchFn: (params: Record<string, unknown>) => Promise<{ data: PaginatedResponse<T> }>;
  pageKey: string;
  defaultSortField: string;
  defaultSortDescending?: boolean;
  filters?: Record<string, unknown>;
}

interface UseServerCollectionResult<T> {
  items: T[];
  total: number;
  loading: boolean;
  error: string | null;
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  totalPages: number;
  paginationProps: PaginationProps;
  sortingColumn: TableProps.SortingColumn<T> | undefined;
  sortingDescending: boolean;
  onSortingChange: (event: { detail: TableProps.SortingState<T> }) => void;
  refresh: () => void;
}

export function useServerCollection<T>(
  options: UseServerCollectionOptions<T>,
): UseServerCollectionResult<T> {
  const { fetchFn, pageKey, defaultSortField, defaultSortDescending = false, filters = {} } = options;
  const { getPageSize } = usePreferences();
  const pageSize = getPageSize(pageKey);

  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [sortField, setSortField] = useState(defaultSortField);
  const [sortDescending, setSortDescending] = useState(defaultSortDescending);

  // Track previous filter/sort/pageSize to reset page on change
  const prevRef = useRef({ filters, sortField, sortDescending, pageSize });

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, unknown> = {
        page,
        page_size: pageSize,
        sort_by: sortField,
        sort_order: sortDescending ? 'desc' : 'asc',
        ...filters,
      };
      // Remove undefined/null values
      Object.keys(params).forEach((key) => {
        if (params[key] === undefined || params[key] === null || params[key] === '') {
          delete params[key];
        }
      });
      const res = await fetchFn(params);
      setItems(res.data.items);
      setTotal(res.data.total);
    } catch {
      setError('Failed to load data.');
    } finally {
      setLoading(false);
    }
  }, [fetchFn, page, pageSize, sortField, sortDescending, filters]);

  // Reset page to 1 when sort/filters/pageSize change
  useEffect(() => {
    const prev = prevRef.current;
    const filtersChanged = JSON.stringify(prev.filters) !== JSON.stringify(filters);
    const sortChanged = prev.sortField !== sortField || prev.sortDescending !== sortDescending;
    const pageSizeChanged = prev.pageSize !== pageSize;

    if (filtersChanged || sortChanged || pageSizeChanged) {
      setPage(1);
    }
    prevRef.current = { filters, sortField, sortDescending, pageSize };
  }, [filters, sortField, sortDescending, pageSize]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const totalPages = total ? Math.ceil(total / pageSize) : 0;

  const onSortingChange = useCallback(
    (event: { detail: TableProps.SortingState<T> }) => {
      const { sortingColumn, isDescending } = event.detail;
      if (sortingColumn.sortingField) {
        setSortField(sortingColumn.sortingField);
      }
      setSortDescending(isDescending ?? false);
    },
    [],
  );

  return {
    items,
    total,
    loading,
    error,
    page,
    setPage,
    pageSize,
    totalPages,
    paginationProps: {
      currentPageIndex: page,
      pagesCount: totalPages,
      onChange: ({ detail }) => setPage(detail.currentPageIndex),
    },
    sortingColumn: sortField ? { sortingField: sortField } : undefined,
    sortingDescending: sortDescending,
    onSortingChange,
    refresh: fetchData,
  };
}
