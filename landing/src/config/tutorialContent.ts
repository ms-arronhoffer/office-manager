// Long-form tutorial bodies, keyed by slug (see ./site.ts for the index metadata).
// Each tutorial renders an intro, a numbered step list, an optional product
// screenshot, and a closing tip.

export interface TutorialStep {
  title: string;
  body: string;
}

export interface TutorialBody {
  intro: string;
  screen?: 'dashboard' | 'lease' | 'maintenance' | 'waivers' | 'analytics';
  steps: TutorialStep[];
  tip?: string;
  next?: string; // slug of the recommended next tutorial
}

export const tutorialContent: Record<string, TutorialBody> = {
  'getting-started': {
    intro:
      "This walkthrough takes you from an empty account to a working portfolio in under an hour. No consultant, no six-month rollout — just the essentials your team needs on day one.",
    screen: 'dashboard',
    steps: [
      { title: 'Create your workspace', body: 'Start your free trial and name your workspace. Portfolio Desk spins up an isolated, multi-tenant environment for your organization — no credit card required.' },
      { title: 'Add your first office', body: 'Create an office with its address, square footage, and landlord. This becomes the anchor that leases, tickets, vendors, and HVAC records attach to.' },
      { title: 'Invite your team', body: 'Send email invites and assign roles — admin, editor, or viewer. Every plan includes unlimited users, so bring the whole facilities team in.' },
      { title: 'Set your first alert', body: 'Turn on notifications for lease expirations and maintenance SLAs so the right person is emailed before a deadline, not after.' },
    ],
    tip: 'Start with one representative office end-to-end before bulk-importing. It makes the patterns obvious and the import that follows much faster.',
    next: 'importing-leases',
  },
  'importing-leases': {
    intro:
      'Bring your existing portfolio in from spreadsheets and PDFs. The guided importer maps your columns to the right fields, and AI can read the lease documents themselves.',
    screen: 'lease',
    steps: [
      { title: 'Prepare your spreadsheet', body: 'Export your current tracker to CSV. Any column layout works — you will map fields in the next step, so there is no rigid template to match.' },
      { title: 'Map your columns', body: 'Upload the CSV and match each column to a lease field: tenant, premises, commencement, expiration, base rent, escalation, and notice window.' },
      { title: 'Attach the source documents', body: 'Upload the lease PDFs to each record. Documents are stored on the lease and become fully searchable across your portfolio.' },
      { title: 'Let AI fill the gaps', body: 'Run AI extraction on an uploaded lease to auto-populate any missing key terms, then review the suggested values before saving.' },
    ],
    tip: 'Numeric and AI-suggested financial values are coerced safely — out-of-range or non-numeric entries are dropped rather than breaking the import.',
    next: 'maintenance-workflow',
  },
  'maintenance-workflow': {
    intro:
      'Take a work order from "just reported" to "resolved" without losing the thread. Tickets keep SLA timers, vendor assignments, photos, and notes in one place.',
    screen: 'maintenance',
    steps: [
      { title: 'Submit a ticket', body: 'Create a ticket against an office, set a priority, and attach photos. The SLA timer starts automatically based on the priority and your rules.' },
      { title: 'Assign a vendor', body: 'Pick a vendor from your directory. They are notified by email, and — with the vendor portal — can update status, complete work, and upload invoices.' },
      { title: 'Track to resolution', body: 'Watch the SLA countdown, add notes, and escalate if it stalls. Everyone sees the same single source of truth.' },
      { title: 'Close and review', body: 'Mark the ticket resolved. It rolls into your SLA compliance metrics and stays in the audit log for good.' },
    ],
    tip: 'Configure escalation rules so a near-breach SLA automatically emails the responsible manager before the deadline passes.',
    next: 'ai-lease-abstraction',
  },
  'ai-lease-abstraction': {
    intro:
      'Stop reading 60-page leases line by line. AI extracts the terms that matter, drafts an abstract, and writes the briefing your leadership actually reads.',
    screen: 'lease',
    steps: [
      { title: 'Upload the lease', body: 'Drop in a PDF or Word document. Portfolio Desk extracts the text first so AI can reliably read every clause.' },
      { title: 'Extract key terms', body: 'AI returns the tenant, dates, rent, escalations, options, and notice windows as structured fields you can review and accept.' },
      { title: 'Generate an abstract', body: 'With one click, AI drafts a clean, shareable lease abstract — perfect for handing to finance or legal.' },
      { title: 'Schedule briefings', body: 'Turn on weekly and monthly AI briefings that summarize upcoming notice periods, expirations, and maintenance across the portfolio.' },
    ],
    tip: 'AI lease detail extraction is available on every plan; AI abstracts and briefings are included on Pro and above.',
    next: 'digital-waivers',
  },
  'digital-waivers': {
    intro:
      'Collect legally sound signatures without paper. Build a template once, then send it to contacts or let visitors sign themselves at a kiosk.',
    screen: 'waivers',
    steps: [
      { title: 'Build a template', body: 'Create a reusable waiver — liability, photo release, contractor site rules, or your own — with the fields you need captured.' },
      { title: 'Send or self-serve', body: 'Email a secure signing link to a named contact, or open the self-serve flow so visitors enter their own details and sign on the spot.' },
      { title: 'Capture consent', body: 'Each signature records the signer, timestamp, IP, and consent — a tamper-evident trail that conforms to ESIGN/UETA standards.' },
      { title: 'Search and manage', body: 'Find any signed waiver by name, email, or title, review the audit trail, and delete requests when retention rules allow.' },
    ],
    tip: 'Signing links are public and token-based, so signers never need an account — but every action is still fully attributed.',
    next: 'analytics-reporting',
  },
  'analytics-reporting': {
    intro:
      'Turn day-to-day activity into the numbers leadership cares about — SLA compliance, cost per square foot, and backlog — then export them in a click.',
    screen: 'analytics',
    steps: [
      { title: 'Read the dashboards', body: 'Open the analytics workspace for portfolio-level KPIs and trends across every office and lease.' },
      { title: 'Track SLA compliance', body: 'Watch compliance trend month over month and drill into the tickets and locations driving the number.' },
      { title: 'Trend your costs', body: 'Follow cost per square foot and maintenance backlog over time to spot problems before they grow.' },
      { title: 'Export for leadership', body: 'Generate polished PDF reports or raw CSV extracts on demand for board decks and finance reviews.' },
    ],
    tip: 'Every record is logged with user, timestamp, and change detail, so your reports are always backed by a full audit trail.',
    next: 'getting-started',
  },
};
