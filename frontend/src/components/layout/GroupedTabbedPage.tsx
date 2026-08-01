import React, { useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import SegmentedControl from '@cloudscape-design/components/segmented-control';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Tabs from '@cloudscape-design/components/tabs';

export interface GroupedTab {
  /** Stable tab id. */
  id: string;
  /** Tab label shown in the tab strip. */
  label: string;
  /** Absolute URL backing this tab (drives selection + deep links). */
  href: string;
  /** Rendered content for the tab (only the active tab mounts). */
  content: React.ReactNode;
}

export interface TabGroup {
  id: string;
  label: string;
  tabs: GroupedTab[];
}

interface GroupedTabbedPageProps {
  groups: TabGroup[];
  /** Optional aria label for the tab strip. */
  ariaLabel?: string;
  /** Rendered when every tab has been filtered out by role or plan. */
  emptyState?: React.ReactNode;
}

/**
 * Two-level, URL-driven navigation for hubs that had grown too many peer tabs
 * to scan. The group rail answers "which part of the workflow am I in" while
 * the tab strip stays scoped to that group.
 *
 * Every tab keeps its original URL, so existing deep links, the back button and
 * global search continue to resolve unchanged.
 */
const GroupedTabbedPage: React.FC<GroupedTabbedPageProps> = ({
  groups,
  ariaLabel,
  emptyState,
}) => {
  const location = useLocation();
  const navigate = useNavigate();

  const populated = useMemo(() => groups.filter((g) => g.tabs.length > 0), [groups]);

  // Pick the tab whose href most specifically matches the current pathname so
  // e.g. `/finance/accounts-payable` wins over `/finance`.
  const active = useMemo(() => {
    const all = populated.flatMap((g) => g.tabs.map((t) => ({ group: g, tab: t })));
    const match = [...all]
      .sort((a, b) => b.tab.href.length - a.tab.href.length)
      .find(
        ({ tab }) =>
          location.pathname === tab.href ||
          location.pathname.startsWith(`${tab.href}/`),
      );
    return match ?? (all.length > 0 ? all[0] : null);
  }, [populated, location.pathname]);

  if (populated.length === 0 || !active) {
    return <>{emptyState ?? null}</>;
  }

  const activeGroup = active.group;

  return (
    <SpaceBetween size="m">
      {populated.length > 1 && (
        <SegmentedControl
          selectedId={activeGroup.id}
          onChange={({ detail }) => {
            const next = populated.find((g) => g.id === detail.selectedId);
            if (next && next.tabs[0].href !== location.pathname) {
              navigate(next.tabs[0].href);
            }
          }}
          label={ariaLabel ? `${ariaLabel} sections` : 'Sections'}
          options={populated.map((g) => ({ id: g.id, text: g.label }))}
        />
      )}
      <Tabs
        ariaLabel={ariaLabel}
        activeTabId={active.tab.id}
        onChange={({ detail }) => {
          const next = activeGroup.tabs.find((t) => t.id === detail.activeTabId);
          if (next && next.href !== location.pathname) {
            navigate(next.href);
          }
        }}
        tabs={activeGroup.tabs.map(({ id, label, content }) => ({ id, label, content }))}
      />
    </SpaceBetween>
  );
};

export default GroupedTabbedPage;
