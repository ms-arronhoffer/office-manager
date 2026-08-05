import React, { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Cards from '@cloudscape-design/components/cards';
import Link from '@cloudscape-design/components/link';
import Box from '@cloudscape-design/components/box';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import TextFilter from '@cloudscape-design/components/text-filter';
import { useAuth } from '@/auth/AuthContext';
import { useEntitlements } from '@/hooks/useEntitlements';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';

interface AdminLink {
  text: string;
  href: string;
  description: string;
  /** Roles allowed to see this link. */
  roles: Array<'admin' | 'editor'>;
  feature?: string;
}

interface AdminGroup {
  id: string;
  label: string;
  href: string;
  links: AdminLink[];
}

// Reorganizes the former 14-item Administration nav group into four intuitive
// buckets. Each entry links to its existing page (routes are unchanged).
const GROUPS: AdminGroup[] = [
  {
    id: 'people',
    label: 'People & Access',
    href: '/administration',
    links: [
      { text: 'Users', href: '/users', description: 'Manage user accounts, roles, and access.', roles: ['admin'] },
      { text: 'Single Sign-On', href: '/admin/sso', description: 'Connect your identity provider so staff sign in with your existing directory.', roles: ['admin'], feature: 'sso' },
      { text: 'Managers', href: '/managers', description: 'Manage office managers and assignments.', roles: ['admin'] },
    ],
  },
  {
    id: 'automation',
    label: 'Automation',
    href: '/administration/automation',
    links: [
      { text: 'Ticket Categories', href: '/ticket-categories', description: 'Define maintenance ticket categories.', roles: ['admin'] },
      { text: 'Maintenance Topics', href: '/maintenance-topics', description: 'Configure maintenance asset and task topics by category.', roles: ['admin', 'editor'], feature: 'maintenance' },
      { text: 'Ticket Templates', href: '/ticket-templates', description: 'Reusable templates for common tickets.', roles: ['admin', 'editor'] },
      { text: 'Recurring Tickets', href: '/recurring-ticket-rules', description: 'Schedule tickets that repeat automatically.', roles: ['admin', 'editor'] },
      { text: 'Email Rules', href: '/email-rules', description: 'Route inbound email into tickets.', roles: ['admin'] },
    ],
  },
  {
    id: 'integrations',
    label: 'Integrations',
    href: '/administration/integrations',
    links: [
      { text: 'API Keys', href: '/api-keys', description: 'Programmatic access credentials.', roles: ['admin'], feature: 'api_access' },
      { text: 'Webhooks', href: '/webhooks', description: 'Outbound event notifications.', roles: ['admin'], feature: 'webhooks' },
      { text: 'Billing', href: '/billing', description: 'Subscription plan and invoices.', roles: ['admin'] },
    ],
  },
  {
    id: 'system',
    label: 'System & Data',
    href: '/administration/system',
    links: [
      { text: 'Personal Settings', href: '/settings', description: 'Your personal preferences: appearance, dashboard layout, notifications, and password.', roles: ['admin', 'editor'] },
      { text: 'Company Settings', href: '/admin/site-settings', description: 'Company branding, contact information, and global application settings.', roles: ['admin'] },
      { text: 'Business Categories', href: '/admin/categories', description: 'Enable or disable Commercial, Residential, and Self Storage lines of business.', roles: ['admin'] },
      { text: 'Support Requests', href: '/support-requests', description: 'Review and forward in-app support requests.', roles: ['admin'] },
      { text: 'Data Dictionary', href: '/data-dictionary', description: 'Reference for data fields and meanings.', roles: ['admin'] },
      { text: 'Audit Log', href: '/activity-log', description: 'Review system and user activity.', roles: ['admin'] },
      { text: 'Trash', href: '/trash', description: 'Restore or purge deleted records.', roles: ['admin'] },
      { text: 'Buildium Migration', href: '/buildium', description: 'Configure and run the Buildium data migration connector.', roles: ['admin'], feature: 'buildium_migration' },
    ],
  },
];

const AdminLinkCards: React.FC<{ links: AdminLink[] }> = ({ links }) => {
  const navigate = useNavigate();
  return (
    <Cards
      items={links}
      trackBy="href"
      cardDefinition={{
        header: (item) => (
          <Link
            fontSize="heading-m"
            onFollow={(e) => {
              e.preventDefault();
              navigate(item.href);
            }}
            href={item.href}
          >
            {item.text}
          </Link>
        ),
        sections: [
          {
            id: 'description',
            content: (item) => <Box color="text-body-secondary">{item.description}</Box>,
          },
        ],
      }}
      cardsPerRow={[{ cards: 1 }, { minWidth: 480, cards: 2 }, { minWidth: 800, cards: 3 }]}
    />
  );
};

/**
 * Administration hub — four tabbed buckets of link cards over the existing
 * admin routes, plus a search box so a setting can be found by name without
 * knowing which bucket it lives in.
 */
const AdministrationPage: React.FC = () => {
  const { user } = useAuth();
  const { hasFeature } = useEntitlements();
  const role = user?.role;
  const [query, setQuery] = useState('');

  const visibleLinks = useCallback(
    (group: AdminGroup) =>
      group.links.filter(
        (link) =>
          role &&
          (link.roles as string[]).includes(role) &&
          (!link.feature || hasFeature(link.feature)),
      ),
    [role, hasFeature],
  );

  // Searching spans every bucket, so a setting is reachable by name alone.
  const searchResults = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return GROUPS.flatMap((group) =>
      visibleLinks(group).map((link) => ({ ...link, groupLabel: group.label })),
    ).filter(
      (link) =>
        link.text.toLowerCase().includes(q) ||
        link.description.toLowerCase().includes(q) ||
        link.groupLabel.toLowerCase().includes(q),
    );
  }, [query, visibleLinks]);

  const tabs: TabbedPageTab[] = GROUPS.map((group) => ({
    group,
    visible: visibleLinks(group),
  }))
    .filter(({ visible }) => visible.length > 0)
    .map(({ group, visible }) => ({
      id: group.id,
      label: group.label,
      href: group.href,
      content: <AdminLinkCards links={visible} />,
    }));

  return (
    <ContentLayout
      header={
        <Header variant="h1" description="Manage people, automation, integrations and organization settings.">
          Administration
        </Header>
      }
    >
      <SpaceBetween size="l">
        <TextFilter
          filteringText={query}
          filteringPlaceholder="Search settings"
          filteringAriaLabel="Search administration settings"
          onChange={({ detail }) => setQuery(detail.filteringText)}
          countText={
            searchResults
              ? `${searchResults.length} match${searchResults.length === 1 ? '' : 'es'}`
              : ''
          }
        />
        {searchResults ? (
          searchResults.length > 0 ? (
            <AdminLinkCards links={searchResults} />
          ) : (
            <Box textAlign="center" padding="l" color="text-body-secondary">
              No settings match “{query}”.
            </Box>
          )
        ) : (
          <TabbedPage ariaLabel="Administration" tabs={tabs} />
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default AdministrationPage;
