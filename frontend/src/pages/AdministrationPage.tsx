import React from 'react';
import { useNavigate } from 'react-router-dom';
import Cards from '@cloudscape-design/components/cards';
import Link from '@cloudscape-design/components/link';
import Box from '@cloudscape-design/components/box';
import { useAuth } from '@/auth/AuthContext';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';

interface AdminLink {
  text: string;
  href: string;
  description: string;
  /** Roles allowed to see this link. */
  roles: Array<'admin' | 'editor'>;
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
      { text: 'Managers', href: '/managers', description: 'Manage office managers and assignments.', roles: ['admin'] },
    ],
  },
  {
    id: 'automation',
    label: 'Automation',
    href: '/administration/automation',
    links: [
      { text: 'Ticket Categories', href: '/ticket-categories', description: 'Define maintenance ticket categories.', roles: ['admin'] },
      { text: 'Maintenance Topics', href: '/maintenance-topics', description: 'Configure maintenance asset and task topics by category.', roles: ['admin', 'editor'] },
      { text: 'Ticket Templates', href: '/ticket-templates', description: 'Reusable templates for common tickets.', roles: ['admin', 'editor'] },
      { text: 'Recurring Tickets', href: '/recurring-ticket-rules', description: 'Schedule tickets that repeat automatically.', roles: ['admin', 'editor'] },
      { text: 'Email Rules', href: '/email-rules', description: 'Route inbound email into tickets.', roles: ['admin'] },
      { text: 'Wizard Configs', href: '/wizard-configs', description: 'Configure guided flows and wizards.', roles: ['admin'] },
      { text: 'Flow Authoring Guide', href: '/wizard-docs', description: 'Documentation for authoring flows.', roles: ['admin'] },
    ],
  },
  {
    id: 'integrations',
    label: 'Integrations',
    href: '/administration/integrations',
    links: [
      { text: 'API Keys', href: '/api-keys', description: 'Programmatic access credentials.', roles: ['admin'] },
      { text: 'Webhooks', href: '/webhooks', description: 'Outbound event notifications.', roles: ['admin'] },
      { text: 'Billing', href: '/billing', description: 'Subscription plan and invoices.', roles: ['admin'] },
    ],
  },
  {
    id: 'system',
    label: 'System & Data',
    href: '/administration/system',
    links: [
      { text: 'Site Settings', href: '/admin/site-settings', description: 'Branding and global application settings.', roles: ['admin'] },
      { text: 'Support Requests', href: '/support-requests', description: 'Review and forward in-app support requests.', roles: ['admin'] },
      { text: 'Data Dictionary', href: '/data-dictionary', description: 'Reference for data fields and meanings.', roles: ['admin'] },
      { text: 'Audit Log', href: '/activity-log', description: 'Review system and user activity.', roles: ['admin'] },
      { text: 'Trash', href: '/trash', description: 'Restore or purge deleted records.', roles: ['admin'] },
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
 * Administration hub — replaces the former 14-item Administration nav group
 * with a single destination organized into four tabbed buckets of link cards.
 * The underlying admin pages keep their existing routes.
 */
const AdministrationPage: React.FC = () => {
  const { user } = useAuth();
  const role = user?.role;

  const tabs: TabbedPageTab[] = GROUPS.map((group) => ({
    group,
    visible: group.links.filter((l) => role && (l.roles as string[]).includes(role)),
  }))
    .filter(({ visible }) => visible.length > 0)
    .map(({ group, visible }) => ({
      id: group.id,
      label: group.label,
      href: group.href,
      content: <AdminLinkCards links={visible} />,
    }));

  return <TabbedPage ariaLabel="Administration" tabs={tabs} />;
};

export default AdministrationPage;
