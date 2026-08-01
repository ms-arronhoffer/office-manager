import React from 'react';
import { useCollection } from '@cloudscape-design/collection-hooks';
import Box from '@cloudscape-design/components/box';
import Pagination from '@cloudscape-design/components/pagination';
import TextFilter from '@cloudscape-design/components/text-filter';
import { usePreferences } from '@/context/PreferencesContext';

interface Options<T> {
  /** Preference key used to remember the page size for this list. */
  entity: string;
  /** Free-text haystack for a row. */
  searchText: (item: T) => string;
  /** Shown when the underlying collection is empty. */
  empty: React.ReactNode;
  /** Placeholder for the filter input. */
  filterPlaceholder?: string;
  defaultPageSize?: number;
  /** Optional initial sort column id. */
  sortingColumn?: { sortingField: string };
}

/**
 * Standard behaviour for in-memory lists: free-text filter, sorting, and
 * pagination with a remembered page size. Endpoints that return a plain array
 * would otherwise render every row at once.
 */
export function useListCollection<T>(allItems: T[], opts: Options<T>) {
  const { getPageSize, setPageSize } = usePreferences();
  const pageSize = getPageSize(opts.entity) ?? opts.defaultPageSize ?? 25;

  const { items, collectionProps, filterProps, filteredItemsCount, paginationProps, actions } =
    useCollection(allItems, {
      filtering: {
        empty: opts.empty,
        noMatch: (
          <Box textAlign="center" padding="m">
            No matches. Try a different search.
          </Box>
        ),
        filteringFunction: (item, text) =>
          opts.searchText(item).toLowerCase().includes((text ?? '').toLowerCase()),
      },
      pagination: { pageSize },
      sorting: opts.sortingColumn ? { defaultState: { sortingColumn: opts.sortingColumn } } : {},
      selection: {},
    });

  const filter = (
    <TextFilter
      {...filterProps}
      filteringPlaceholder={opts.filterPlaceholder ?? 'Search'}
      countText={
        filterProps.filteringText
          ? `${filteredItemsCount ?? 0} match${filteredItemsCount === 1 ? '' : 'es'}`
          : ''
      }
    />
  );

  const pagination = <Pagination {...paginationProps} />;

  return {
    items,
    collectionProps,
    filter,
    pagination,
    filteredItemsCount,
    actions,
    /** Rows the user has ticked. Requires `selectionType` on the Table. */
    selectedItems: (collectionProps.selectedItems ?? []) as T[],
    clearSelection: () => actions.setSelectedItems([]),
    pageSize,
    setPageSize: (n: number) => setPageSize(opts.entity, n),
  };
}

export default useListCollection;
