/**
 * Single source of truth for which screens get captured, for which
 * persona, and where the resulting image lands in the landing site.
 *
 * This file is intentionally framework-agnostic data (no Playwright
 * imports) so the landing site's tutorial content config can eventually
 * import the same `screenshotId` values without pulling in test tooling.
 *
 * Personas mirror the app's actual access model:
 *   - Internal roles: admin, editor, accountant, viewer (see frontend/src/auth/RoleGuard.tsx)
 *   - External, token-gated portals: resident, owner, vendor, client
 *
 * `path` is relative to the app's base URL (internal app) or is the full
 * portal path (external personas carry their own token in the URL).
 */

export type Persona = 'admin' | 'editor' | 'accountant' | 'viewer' | 'resident' | 'owner' | 'vendor' | 'client';

export interface ScreenshotSpec {
  /** Stable id — becomes the file name (role-slug/id.png) and the id referenced from tutorial content. */
  id: string;
  /** Route to visit once authenticated as `persona`. */
  path: string;
  /** Human description, used for alt text and for the capture log. */
  description: string;
  /** Optional selector to wait for before taking the screenshot (beyond the default app-shell wait). */
  waitForSelector?: string;
  /** Optional extra delay (ms) after the wait, for charts/animations to settle. */
  settleMs?: number;
}

export interface PersonaSpec {
  persona: Persona;
  label: string;
  screenshots: ScreenshotSpec[];
}

export const personas: PersonaSpec[] = [
  {
    persona: 'admin',
    label: 'Admin',
    screenshots: [
      { id: 'dashboard', path: '/', description: 'Portfolio dashboard hub after login' },
      { id: 'offices', path: '/offices', description: 'Offices directory list' },
      { id: 'users', path: '/users', description: 'Team members and role management' },
      { id: 'site-settings', path: '/admin/site-settings', description: 'Organization site settings' },
      { id: 'api-keys', path: '/api-keys', description: 'API keys management' },
      { id: 'webhooks', path: '/webhooks', description: 'Webhook subscriptions' },
      { id: 'activity-log', path: '/activity-log', description: 'Full audit / activity log' },
    ],
  },
  {
    persona: 'editor',
    label: 'Editor',
    screenshots: [
      { id: 'leases', path: '/leases', description: 'Lease register' },
      { id: 'lease-detail', path: '/leases/{leaseId}', description: 'Lease detail with key terms' },
      { id: 'maintenance-tickets', path: '/maintenance-tickets', description: 'Maintenance ticket queue' },
      { id: 'hvac', path: '/hvac', description: 'HVAC contracts and equipment' },
      { id: 'transitions', path: '/transitions', description: 'Office transition checklist' },
      { id: 'waivers', path: '/waivers', description: 'Digital waiver templates' },
      { id: 'operating-expenses', path: '/finance/operating-expenses', description: 'Operating expense tracking' },
      { id: 'administration', path: '/administration', description: 'Administration hub' },
      { id: 'insurance-certificates', path: '/insurance-certificates', description: 'Insurance certificate tracking' },
    ],
  },
  {
    persona: 'accountant',
    label: 'Accountant',
    screenshots: [
      { id: 'general-ledger', path: '/finance/general-ledger', description: 'General ledger and journal entries' },
      { id: 'financial-statements', path: '/finance/financial-statements', description: 'Financial statements' },
      { id: 'accounts-payable', path: '/finance/accounts-payable', description: 'Vendor bills and payments (AP)' },
      { id: 'accounts-receivable', path: '/finance/accounts-receivable', description: 'Tenant billing and receivables (AR)' },
      { id: 'budgeting', path: '/finance/budgeting', description: 'Budget vs actuals' },
      { id: 'owners', path: '/residential/owners', description: 'Owner / trust accounting' },
      { id: 'rent-collection', path: '/residential/rent', description: 'Rent collection dashboard' },
    ],
  },
  {
    persona: 'viewer',
    label: 'Viewer',
    screenshots: [
      { id: 'analytics', path: '/dashboard/analytics', description: 'Portfolio analytics dashboard' },
      { id: 'reports', path: '/dashboard/reports', description: 'Report exports' },
      { id: 'lease-calendar', path: '/leases/calendar', description: 'Lease expiration calendar' },
      { id: 'residential-units', path: '/residential', description: 'Residential units overview' },
      { id: 'vacancy-listings', path: '/residential/listings', description: 'Vacancy listing marketing pages' },
      { id: 'announcements', path: '/residential/announcements', description: 'Resident announcements' },
    ],
  },
];

export const externalPersonas: PersonaSpec[] = [
  {
    persona: 'resident',
    label: 'Resident',
    screenshots: [
      { id: 'home', path: '', description: 'Resident portal home: lease, balance, announcements' },
    ],
  },
  {
    persona: 'owner',
    label: 'Property owner',
    screenshots: [
      { id: 'home', path: '', description: 'Owner portal home: statements and distributions' },
    ],
  },
  {
    persona: 'vendor',
    label: 'Vendor',
    screenshots: [
      { id: 'home', path: '', description: 'Vendor portal home: assigned work orders' },
    ],
  },
  {
    persona: 'client',
    label: 'Landlord / client',
    screenshots: [
      { id: 'home', path: '', description: 'Client portal home: property and contact details' },
    ],
  },
];
