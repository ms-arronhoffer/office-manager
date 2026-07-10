// Central navigation + content config shared across all pages of the marketing site.
// Page links are real routes (multi-page site). External app URLs are wired at
// runtime from /config.js via [data-href] so no rebuild is needed per deployment.

export interface NavLink {
  label: string;
  href: string;
}

export const primaryNav: NavLink[] = [
  { label: 'Features', href: '/features' },
  { label: 'Tutorials', href: '/tutorials' },
  { label: 'Pricing', href: '/pricing' },
  { label: 'Contact', href: '/contact' },
];

// Tutorials are sectioned by "who can actually do this" rather than by
// feature area. Internal roles (admin/editor/accountant/viewer) are ordered
// by permission tier, lowest first; external, token-gated portal personas
// (resident/owner/vendor/client) are separate because they never log in
// with an internal role at all.
//
// A task available to more than one internal role is always homed under the
// *lowest* tier that can reach it (e.g. a page open to viewer+editor+admin
// is a Viewer tutorial; a page open to accountant+admin is an Accountant
// tutorial). `viewer` is a real, first-class tier here even though it has
// no explicit RoleGuard in the app, it is simply the default/fallback
// role every authenticated internal user has.
export type RoleGroup = 'internal' | 'portal';

export interface RoleSection {
  slug: string;
  label: string;
  tagline: string;
  group: RoleGroup;
}

export const roleSections: RoleSection[] = [
  { slug: 'viewer', label: 'Viewer', tagline: 'Read-only portfolio visibility', group: 'internal' },
  { slug: 'editor', label: 'Editor', tagline: 'Day-to-day leasing & operations', group: 'internal' },
  { slug: 'accountant', label: 'Accountant', tagline: 'Books, billing & owner accounting', group: 'internal' },
  { slug: 'admin', label: 'Admin', tagline: 'Team, security & organization settings', group: 'internal' },
  { slug: 'resident', label: 'Resident portal', tagline: 'For your residential tenants', group: 'portal' },
  { slug: 'owner', label: 'Owner portal', tagline: 'For property owners you manage for', group: 'portal' },
  { slug: 'vendor', label: 'Vendor portal', tagline: 'For contractors and service vendors', group: 'portal' },
  { slug: 'client', label: 'Client portal', tagline: 'For commercial landlords & clients', group: 'portal' },
];

export const tutorials = [
  {
    slug: 'viewer-guide',
    title: 'Viewer Guide: Portfolio Visibility & Reporting',
    summary:
      'Everything a read-only teammate can do out of the box: analytics dashboards, report exports, the lease expiration calendar, residential unit and vacancy overviews, and resident announcements.',
    minutes: 8,
    level: 'Beginner',
    topics: ['Analytics', 'Reporting', 'Residential'],
    role: 'viewer',
  },
  {
    slug: 'editor-guide',
    title: 'Editor Guide: Leasing, Maintenance & Operations',
    summary:
      'Run the day-to-day: the lease register and lease detail pages, the maintenance ticket queue, HVAC contracts, office transitions, digital waivers, operating expenses, the administration hub, and insurance certificate tracking.',
    minutes: 14,
    level: 'Intermediate',
    topics: ['Leases', 'Maintenance', 'Administration'],
    role: 'editor',
  },
  {
    slug: 'accountant-guide',
    title: 'Accountant Guide: Books, Billing & Owner Accounting',
    summary:
      'Work the general ledger and journal entries, financial statements, accounts payable and receivable, budget vs. actuals, owner/trust accounting, and the rent collection dashboard.',
    minutes: 12,
    level: 'Intermediate',
    topics: ['General Ledger', 'AP/AR', 'Owner Accounting'],
    role: 'accountant',
  },
  {
    slug: 'admin-guide',
    title: 'Admin Guide: Team, Security & Organization Settings',
    summary:
      'Set up the organization from scratch: the portfolio dashboard, offices directory, team members and role assignment, organization site settings, API keys, webhooks, and the full activity/audit log.',
    minutes: 12,
    level: 'Advanced',
    topics: ['Onboarding', 'Security', 'Audit'],
    role: 'admin',
  },
  {
    slug: 'resident-portal-guide',
    title: 'Resident Portal: What Your Tenants See',
    summary:
      'A tour of the self-serve resident portal: lease details, account balance, maintenance requests, documents, and announcements, from the invite link to the portal home.',
    minutes: 5,
    level: 'Beginner',
    topics: ['Resident Portal', 'Self-Serve'],
    role: 'resident',
  },
  {
    slug: 'owner-portal-guide',
    title: 'Owner Portal: What Property Owners See',
    summary:
      'A tour of the owner portal that gives the property owners you manage for their own view of statements and distributions, without giving them access to your internal tools.',
    minutes: 5,
    level: 'Beginner',
    topics: ['Owner Portal', 'Self-Serve'],
    role: 'owner',
  },
  {
    slug: 'vendor-portal-guide',
    title: 'Vendor Portal: What Contractors See',
    summary:
      'A tour of the vendor work portal: assigned work orders, status updates, and the flow a contractor uses to close out a maintenance ticket.',
    minutes: 5,
    level: 'Beginner',
    topics: ['Vendor Portal', 'Maintenance'],
    role: 'vendor',
  },
  {
    slug: 'client-portal-guide',
    title: 'Client Portal: What Commercial Landlords See',
    summary:
      'A tour of the client portal for commercial landlords: property and contact details shared without exposing your internal management tools.',
    minutes: 5,
    level: 'Beginner',
    topics: ['Client Portal', 'Self-Serve'],
    role: 'client',
  },
];

export type Tutorial = (typeof tutorials)[number];

