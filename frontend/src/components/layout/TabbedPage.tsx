import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Tabs from '@cloudscape-design/components/tabs';

export interface TabbedPageTab {
  /** Stable tab id. */
  id: string;
  /** Tab label shown in the tab strip. */
  label: string;
  /** Absolute URL backing this tab (drives selection + deep links). */
  href: string;
  /** Rendered content for the tab (only the active tab mounts). */
  content: React.ReactNode;
}

interface TabbedPageProps {
  tabs: TabbedPageTab[];
  /** Optional aria label for the tab strip. */
  ariaLabel?: string;
}

/**
 * A thin container that renders a set of existing pages as URL-driven tabs.
 *
 * The active tab is derived from the current pathname so deep links, the
 * browser back button, and the global search bar keep working. Selecting a
 * tab navigates to that tab's href rather than swapping local state, keeping
 * the URL the single source of truth.
 */
const TabbedPage: React.FC<TabbedPageProps> = ({ tabs, ariaLabel }) => {
  const location = useLocation();
  const navigate = useNavigate();

  if (tabs.length === 0) {
    return null;
  }

  // Pick the tab whose href most specifically matches the current pathname.
  // Longer hrefs win so e.g. `/finance/rent-roll` beats `/finance`.
  const active =
    [...tabs]
      .sort((a, b) => b.href.length - a.href.length)
      .find(
        (t) =>
          location.pathname === t.href ||
          location.pathname.startsWith(`${t.href}/`),
      ) ?? tabs[0];

  return (
    <Tabs
      ariaLabel={ariaLabel}
      activeTabId={active.id}
      onChange={({ detail }) => {
        const next = tabs.find((t) => t.id === detail.activeTabId);
        if (next && next.href !== location.pathname) {
          navigate(next.href);
        }
      }}
      tabs={tabs.map(({ id, label, content }) => ({ id, label, content }))}
    />
  );
};

export default TabbedPage;
