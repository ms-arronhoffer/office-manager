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

export const tutorials = [
  {
    slug: 'getting-started',
    title: 'Getting Started: Your First Hour',
    summary:
      'Stand up your portfolio, invite your team, and configure your first alerts — from empty account to operational in under 60 minutes.',
    minutes: 8,
    level: 'Beginner',
    topics: ['Onboarding', 'Setup', 'Team'],
  },
  {
    slug: 'importing-leases',
    title: 'Importing Leases & Office Data',
    summary:
      'Bring your existing spreadsheets and lease PDFs into the platform with the guided importer and document upload.',
    minutes: 10,
    level: 'Beginner',
    topics: ['Leases', 'Import', 'Documents'],
  },
  {
    slug: 'maintenance-workflow',
    title: 'Running a Maintenance Workflow',
    summary:
      'From a submitted work order to a resolved ticket — assign vendors, track SLA timers, and keep a full audit trail.',
    minutes: 9,
    level: 'Intermediate',
    topics: ['Tickets', 'Vendors', 'SLA'],
  },
  {
    slug: 'ai-lease-abstraction',
    title: 'AI Lease Abstraction & Briefings',
    summary:
      'Let AI read an uploaded lease, extract the key terms, draft an abstract, and write your weekly portfolio briefing.',
    minutes: 7,
    level: 'Intermediate',
    topics: ['AI', 'Leases', 'Reporting'],
  },
  {
    slug: 'digital-waivers',
    title: 'Sending Digital Waivers & e-Signatures',
    summary:
      'Build a reusable waiver template, send it to contacts or self-serve visitors, and capture a tamper-evident audit trail.',
    minutes: 6,
    level: 'Intermediate',
    topics: ['Waivers', 'e-Signature', 'Compliance'],
  },
  {
    slug: 'analytics-reporting',
    title: 'Analytics, Reporting & Exports',
    summary:
      'Read portfolio-level dashboards, track SLA compliance, and export board-ready PDF and CSV reports.',
    minutes: 6,
    level: 'Advanced',
    topics: ['Analytics', 'Reporting', 'Export'],
  },
];

export type Tutorial = (typeof tutorials)[number];
