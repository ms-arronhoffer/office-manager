import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { usePagedItems } from '@/hooks/usePagedItems';

const items = (count: number) => Array.from({ length: count }, (_, i) => ({ id: i }));

describe('usePagedItems', () => {
  it('returns everything on one page when the collection is small', () => {
    const { result } = renderHook(() => usePagedItems(items(5), 25));

    expect(result.current.pageItems).toHaveLength(5);
    expect(result.current.pagesCount).toBe(1);
    expect(result.current.isPaginated).toBe(false);
  });

  it('slices a large collection into bounded pages', () => {
    const { result } = renderHook(() => usePagedItems(items(120), 25));

    expect(result.current.pageItems).toHaveLength(25);
    expect(result.current.pagesCount).toBe(5);
    expect(result.current.isPaginated).toBe(true);
    expect(result.current.totalCount).toBe(120);
  });

  it('returns the requested page', () => {
    const { result } = renderHook(() => usePagedItems(items(120), 25));

    act(() => result.current.setCurrentPageIndex(3));

    expect(result.current.pageItems[0]).toEqual({ id: 50 });
    expect(result.current.pageItems).toHaveLength(25);
  });

  it('returns a short final page', () => {
    const { result } = renderHook(() => usePagedItems(items(30), 25));

    act(() => result.current.setCurrentPageIndex(2));

    expect(result.current.pageItems).toHaveLength(5);
  });

  it('clamps the page when the collection shrinks', () => {
    const { result, rerender } = renderHook(
      ({ data }) => usePagedItems(data, 25),
      { initialProps: { data: items(120) } },
    );

    act(() => result.current.setCurrentPageIndex(5));
    expect(result.current.currentPageIndex).toBe(5);

    // A filter or refresh leaves far fewer rows; the view must not be stranded
    // on a page that no longer exists.
    rerender({ data: items(10) });

    expect(result.current.currentPageIndex).toBe(1);
    expect(result.current.pageItems).toHaveLength(10);
  });

  it('handles an empty collection', () => {
    const { result } = renderHook(() => usePagedItems([], 25));

    expect(result.current.pageItems).toHaveLength(0);
    expect(result.current.pagesCount).toBe(1);
    expect(result.current.isPaginated).toBe(false);
  });
});
