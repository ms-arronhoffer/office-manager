import React, { useMemo, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import TextFilter from '@cloudscape-design/components/text-filter';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Link from '@cloudscape-design/components/link';
import Alert from '@cloudscape-design/components/alert';
import { useNavigate } from 'react-router-dom';

/**
 * A single how-to article inside a help topic. Steps are rendered as an
 * ordered list; tips are rendered as an informational callout.
 */
interface HelpArticle {
  title: string;
  summary: string;
  steps: string[];
  tips?: string[];
}

/**
 * A collection of related how-to articles, roughly matching a navigation area
 * of the application.
 */
interface HelpTopic {
  id: string;
  title: string;
  description: string;
  articles: HelpArticle[];
}

const HELP_TOPICS: HelpTopic[] = [
  {
    id: 'getting-started',
    title: 'Getting started',
    description: 'Sign in, find your way around, and understand what you can do.',
    articles: [
      {
        title: 'Signing in',
        summary: 'Access the application with your account.',
        steps: [
          'Open the application URL provided by your administrator and you will land on the sign-in page.',
          'Sign in with your email and password, or use "Continue with Google" if single sign-on is enabled for your organization.',
          'If two-factor authentication (2FA) is turned on for your account, enter the 6-digit code from your authenticator app when prompted.',
          'If you were invited by email, follow the link in the invitation to set your password and complete sign-up.',
        ],
        tips: [
          'Forgot your password? Use the "Forgot password" link on the sign-in page to receive a reset email.',
          'For security, you are automatically warned before your session times out and can extend it with a single click.',
        ],
      },
      {
        title: 'Finding your way around',
        summary: 'The layout of the application and how to navigate it.',
        steps: [
          'Use the left-hand side navigation to move between areas such as Dashboard, Commercial, Residential, Operations, Maintenance, Finance, and Settings.',
          'Collapse or expand the side navigation using the arrow at its edge; your preference is remembered between visits.',
          'The top bar holds global search, notifications, support, light/dark mode, and your profile menu.',
          'Use the breadcrumbs near the top of each page to see where you are and jump back to a parent page.',
        ],
        tips: [
          'Many areas (Dashboard, Finance, Residential, Administration) are organized into tabs — the tabs update the page without a full reload.',
          'You can pin frequently used offices so they appear at the top of the side navigation.',
        ],
      },
      {
        title: 'Understanding roles and permissions',
        summary: 'What you can see and do depends on your assigned role.',
        steps: [
          'Viewer — read-only access to most records; cannot create or edit.',
          'Editor — can create and edit operational records such as offices, leases, tickets, and vendors.',
          'Accountant — can access the Finance area, including the general ledger, statements, AP/AR, and owner/trust accounting.',
          'Admin — full access, including user management, administration, and site settings.',
        ],
        tips: [
          'If a menu item or button is missing, your role may not include that permission — ask an administrator if you need access.',
          'Some features (for example, Platform administration) are only visible to super administrators.',
        ],
      },
      {
        title: 'Setting your personal preferences',
        summary: 'Tailor the interface to how you work.',
        steps: [
          'Open the profile menu in the top-right corner and choose Settings, or click Settings in the side navigation.',
          'Switch between light and dark mode using the sun/moon toggle in the top bar.',
          'Update your display name, notification preferences, and (if enabled) two-factor authentication from the Settings page.',
        ],
      },
    ],
  },
  {
    id: 'dashboard',
    title: 'Dashboard & insights',
    description: 'Get a portfolio-wide overview and drill into analytics, reports, and SLAs.',
    articles: [
      {
        title: 'Reading the dashboard',
        summary: 'The dashboard is your home page and summarizes portfolio health.',
        steps: [
          'Open the Dashboard from the top of the side navigation (or click the app name in the top bar).',
          'Review the summary cards for key metrics such as active leases, open maintenance tickets, and upcoming renewals.',
          'Switch between the Financial, Analytics, Reports, and SLA tabs to focus on a specific view.',
          'Click any metric or chart element to drill down into the underlying records.',
        ],
      },
      {
        title: 'Running reports and analytics',
        summary: 'Analyze trends and export data.',
        steps: [
          'Open the Analytics or Reports tab on the Dashboard.',
          'Choose the report or chart you need and adjust any available filters (date range, office, category).',
          'Export the results to PDF or CSV where an export option is offered.',
        ],
        tips: ['SLA dashboards highlight tickets at risk of breaching their response or resolution targets.'],
      },
    ],
  },
  {
    id: 'commercial',
    title: 'Commercial property management',
    description: 'Manage offices, commercial leases, landlords, property managers, and space.',
    articles: [
      {
        title: 'Managing offices',
        summary: 'Offices are the core locations in your portfolio.',
        steps: [
          'Go to Commercial → Offices to see the list of offices.',
          'Use the search box and column filters to find a specific office; sort columns by clicking their headers.',
          'Click "Create office" to add a new location, filling in the address, manager, and other details.',
          'Click any office to open its detail page, where you can view and edit leases, vendors, transitions, and attachments.',
        ],
        tips: ['Pin an office from its detail page to keep it handy at the top of the side navigation.'],
      },
      {
        title: 'Managing commercial leases',
        summary: 'Track lease terms, key dates, and documents.',
        steps: [
          'Go to Commercial → Leases to browse all leases, or open a lease from within an office.',
          'Click "Create lease" and complete the term dates, rent, and status fields.',
          'Set the lease status (for example active, pending, or expired) to keep the portfolio view accurate.',
          'Attach the executed lease document and any amendments to keep everything in one place.',
          'Use the Lease Calendar to visualize commencement, expiry, and option dates across the portfolio.',
        ],
        tips: ['Upcoming critical dates surface on the dashboard so renewals are not missed.'],
      },
      {
        title: 'Landlords, property management, and space',
        summary: 'Maintain the parties and physical space behind each office.',
        steps: [
          'Use Commercial → Landlords to record landlord contacts and link them to offices and leases.',
          'Use Commercial → Property Management to manage the companies and managers responsible for locations.',
          'Use Commercial → Space Management to track square footage, suites, and how space is allocated.',
        ],
      },
    ],
  },
  {
    id: 'residential',
    title: 'Residential property management',
    description: 'Manage rental units, residents, leases, applications, listings, and owners.',
    articles: [
      {
        title: 'Units and residents',
        summary: 'The foundation of residential management.',
        steps: [
          'Go to Residential → Units to add and manage rental units and their attributes.',
          'Go to Residential → Residents to add residents and store their contact details and documents.',
          'Open a resident to manage their leases, attachments, and communication history.',
        ],
      },
      {
        title: 'Resident leases and e-signing',
        summary: 'Create leases from templates and collect signatures online.',
        steps: [
          'Create reusable lease documents under Residential → Lease Templates, including custom merge fields.',
          'From Residential → Resident Leases, create a lease from a template for a specific resident.',
          'Send the lease for e-signature — each party receives an email link to review and sign online.',
          'Track signing progress and download the completed, signed lease when everyone has signed.',
        ],
      },
      {
        title: 'Applications and screening',
        summary: 'Run an online leasing funnel from application to approval.',
        steps: [
          'Build an application form under Residential → Application Templates, defining the fields applicants must complete.',
          'Send an application to a prospect; they open a private link to fill in their details and e-sign.',
          'Review submitted applications under Residential → Applications & Screening and move them through the stages (viewed, in review, screening, approved or denied).',
          'When approved, convert the application into a lease.',
        ],
      },
      {
        title: 'Vacancy listings and announcements',
        summary: 'Market vacancies and communicate with residents.',
        steps: [
          'Create listings under Residential → Vacancy Listings and publish them.',
          'Syndicate a published listing to external portals from the listing to widen its reach.',
          'Use Residential → Announcements to broadcast notices to residents.',
        ],
      },
      {
        title: 'Rent collection, owners, and trust accounting',
        summary: 'Financial features for residential portfolios (accountant/admin).',
        steps: [
          'Use Residential → Rent Collection to record and track rent payments.',
          'Use Residential → Owners & Trust to manage property owners, their statements, distributions, and trust accounts.',
          'Owner ledger activity posts automatically to the general ledger so books stay in sync.',
        ],
      },
    ],
  },
  {
    id: 'operations',
    title: 'Maintenance & operations',
    description: 'Handle maintenance tickets, inspections, vendors, transitions, and compliance.',
    articles: [
      {
        title: 'Working with maintenance tickets',
        summary: 'Log, assign, and resolve maintenance requests.',
        steps: [
          'Go to Operations → Maintenance Tickets to see all requests and their status.',
          'Click "Create ticket", select the office and category, describe the issue, and set the priority.',
          'Assign the ticket to a vendor or team member and track it through to resolution.',
          'Open a ticket to add comments, attachments, and status updates; the activity is recorded for auditing.',
        ],
        tips: [
          'Use Ticket Templates and Recurring Ticket rules (under Administration) to automate routine work.',
          'SLA targets flag tickets that are approaching or past their response/resolution deadlines.',
        ],
      },
      {
        title: 'Inspections',
        summary: 'Schedule and record property inspections.',
        steps: [
          'Go to Operations → Inspections to view scheduled and completed inspections.',
          'Create an inspection, complete the checklist, and attach photos or reports.',
        ],
      },
      {
        title: 'Vendors',
        summary: 'Maintain your vendor directory and their assignments.',
        steps: [
          'Go to Operations → Vendors to add and manage vendors and their contact details.',
          'Associate vendors with the offices they service.',
          'Open a vendor to see assigned tickets, contracts, and insurance certificates.',
        ],
      },
      {
        title: 'Transitions, insurance, and waivers',
        summary: 'Track move-in/move-out transitions and compliance documents.',
        steps: [
          'Use Operations → Transitions to manage office openings, closures, and relocations step by step.',
          'Use Operations → Insurance Certificates to track certificates and their expiry dates (editor/admin).',
          'Use Operations → Digital Waivers to send waivers for electronic signature (editor/admin).',
        ],
      },
    ],
  },
  {
    id: 'maintenance-systems',
    title: 'Building systems maintenance',
    description: 'Track HVAC and other building systems, contracts, and service history.',
    articles: [
      {
        title: 'HVAC and building systems',
        summary: 'Keep building systems serviced and compliant.',
        steps: [
          'Open the Maintenance section and choose Overview or a specific system (HVAC, Fire & Life Safety, Plumbing & Backflow, Refuse & Waste, Exterior & Structural, Elevators & Lifts).',
          'Review upcoming and overdue service items for each system.',
          'Manage HVAC service contracts, including vendors, coverage, and renewal dates.',
        ],
      },
    ],
  },
  {
    id: 'finance',
    title: 'Finance & accounting',
    description: 'Rent roll, general ledger, statements, AP/AR, reconciliation, budgeting, and tax.',
    articles: [
      {
        title: 'Rent roll and operating expenses',
        summary: 'The starting point for portfolio finances.',
        steps: [
          'Go to Finance → Rent Roll to review rent obligations across the portfolio.',
          'Use Finance → Operating Expenses to record and categorize expenses (editor/admin).',
        ],
      },
      {
        title: 'General ledger and financial statements',
        summary: 'Full double-entry accounting (accountant/admin).',
        steps: [
          'Use Finance → General Ledger to view journal entries and account balances.',
          'Use Finance → Financial Statements to produce the balance sheet, income statement, and related reports.',
          'Accounting periods use a close-approval workflow: request a close, then a different user approves it. All changes are recorded in an audit log.',
        ],
        tips: ['Once a period is closed, entries in that period are locked to protect the books.'],
      },
      {
        title: 'AP, AR, CAM, reconciliation, budgeting, and tax',
        summary: 'The full finance toolset.',
        steps: [
          'Use Finance → Accounts Payable to enter vendor bills and record payments; postings flow to the general ledger.',
          'Use Finance → Accounts Receivable to track amounts owed to you.',
          'Use Finance → CAM to manage common area maintenance reconciliations.',
          'Use Finance → Bank Reconciliation to match transactions against bank statements.',
          'Use Finance → Budgeting to plan and compare against actuals.',
          'Use Finance → Tax / 1099 to prepare year-end vendor tax reporting.',
          'Use Finance → Lease Lifecycle for lease accounting across the term.',
        ],
      },
    ],
  },
  {
    id: 'portals',
    title: 'External portals',
    description: 'Invite residents, owners, vendors, and clients to their own self-service portals.',
    articles: [
      {
        title: 'Inviting people to a portal',
        summary: 'Give external parties limited, self-service access.',
        steps: [
          'From a resident record, use the portal invite action to email the resident a sign-up link for the Resident Portal.',
          'From an owner record, invite the owner to the Owner Portal to view statements and distributions.',
          'Vendors and clients have their own portals for the information relevant to them.',
        ],
        tips: ['Portal users only see their own data — they cannot access the rest of the application.'],
      },
    ],
  },
  {
    id: 'productivity',
    title: 'Productivity features',
    description: 'Search, the AI assistant, notifications, keyboard shortcuts, and support.',
    articles: [
      {
        title: 'Global search',
        summary: 'Jump to any record quickly.',
        steps: [
          'Click the search box in the top bar, or press Ctrl + K, to focus global search.',
          'Type a name, number, or keyword to search across the portfolio.',
          'Select a result to open the corresponding record.',
        ],
      },
      {
        title: 'AI portfolio assistant',
        summary: 'Ask questions about your portfolio in plain language.',
        steps: [
          'Open the AI assistant using the assistant icon in the top-right toolbar, or press Ctrl + J.',
          'Ask a question about your data; the assistant answers using information from across the system and cites its sources.',
          'Close the assistant with the same shortcut or by clicking its icon again.',
        ],
      },
      {
        title: 'Notifications',
        summary: 'Stay informed about relevant activity.',
        steps: [
          'Click the bell icon in the top bar to see recent notifications.',
          'Open a notification to jump to the related record.',
        ],
      },
      {
        title: 'Keyboard shortcuts',
        summary: 'Work faster with the keyboard.',
        steps: [
          'Press ? at any time to open the keyboard shortcuts reference.',
          'Ctrl + K focuses global search; Ctrl + J toggles the AI assistant; Escape closes modals and dialogs.',
        ],
      },
      {
        title: 'Getting support',
        summary: 'Reach your administrators when you need help.',
        steps: [
          'Click the Support button in the top bar to submit a support request.',
          'Describe your question or issue and submit; administrators receive and respond to the request.',
        ],
      },
    ],
  },
  {
    id: 'administration',
    title: 'Administration & settings',
    description: 'Admin-only tools for users, automation, integrations, and system configuration.',
    articles: [
      {
        title: 'Managing users and access',
        summary: 'Control who can use the system and what they can do (admin).',
        steps: [
          'Open Administration to manage users, roles, and organization-level settings.',
          'Invite new users by email and assign them a role (viewer, editor, accountant, or admin).',
          'Review the Activity Log to audit changes across the system.',
        ],
      },
      {
        title: 'Automation and integrations',
        summary: 'Extend and connect the system (admin).',
        steps: [
          'Configure email rules, ticket templates, and recurring ticket rules to automate routine work.',
          'Manage API keys and webhooks to integrate with external systems.',
          'Adjust site settings, such as the application name and branding, from the administration area.',
        ],
      },
      {
        title: 'Recovering deleted records',
        summary: 'Many records are soft-deleted and can be restored (admin).',
        steps: [
          'Open Trash from the administration tools to see recently deleted records.',
          'Restore a record to bring it back, or permanently remove it if it is no longer needed.',
        ],
      },
    ],
  },
];

function articleMatches(article: HelpArticle, term: string): boolean {
  const haystack = [article.title, article.summary, ...article.steps, ...(article.tips ?? [])]
    .join(' ')
    .toLowerCase();
  return haystack.includes(term);
}

function topicMatches(topic: HelpTopic, term: string): boolean {
  if (!term) return true;
  return (
    topic.title.toLowerCase().includes(term) ||
    topic.description.toLowerCase().includes(term) ||
    topic.articles.some((a) => articleMatches(a, term))
  );
}

const HelpPage: React.FC = () => {
  const navigate = useNavigate();
  const [filterText, setFilterText] = useState('');

  const term = filterText.trim().toLowerCase();

  const visibleTopics = useMemo(
    () =>
      HELP_TOPICS.map((topic) => {
        // When searching, show every article for a topic whose title/description
        // matches; otherwise only the articles that match the term.
        const topicHeaderMatches =
          topic.title.toLowerCase().includes(term) || topic.description.toLowerCase().includes(term);
        const articles =
          term && !topicHeaderMatches ? topic.articles.filter((a) => articleMatches(a, term)) : topic.articles;
        return { topic, articles };
      }).filter(({ topic, articles }) => topicMatches(topic, term) && articles.length > 0),
    [term],
  );

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[{ text: 'Help', href: '/help' }]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Step-by-step guidance for using every part of the system. Browse the topics below or search for a task."
          >
            Help &amp; User Guide
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        <Container>
          <SpaceBetween size="s">
            <Box variant="p">
              Welcome! This guide explains how to use the features of the application. Expand a
              topic to see how-to articles, or use search to jump straight to a task. What you can
              access depends on your role — if you don&apos;t see a feature described here, you may
              not have permission for it.
            </Box>
            <Box variant="small" color="text-body-secondary">
              Quick links:{' '}
              {HELP_TOPICS.map((topic, i) => (
                <React.Fragment key={topic.id}>
                  {i > 0 && ' · '}
                  <Link
                    href={`#${topic.id}`}
                    onFollow={(e) => {
                      e.preventDefault();
                      document.getElementById(topic.id)?.scrollIntoView({ behavior: 'smooth' });
                    }}
                  >
                    {topic.title}
                  </Link>
                </React.Fragment>
              ))}
            </Box>
          </SpaceBetween>
        </Container>

        <TextFilter
          filteringText={filterText}
          onChange={({ detail }) => setFilterText(detail.filteringText)}
          filteringPlaceholder="Search help topics and tasks..."
          filteringAriaLabel="Search help"
        />

        {visibleTopics.length === 0 ? (
          <Alert type="info" header="No results">
            No help articles match &ldquo;{filterText}&rdquo;. Try a different search term, or clear
            the search to browse all topics.
          </Alert>
        ) : (
          visibleTopics.map(({ topic, articles }) => (
            <div key={topic.id} id={topic.id}>
              <Container
                header={
                  <Header variant="h2" description={topic.description}>
                    <SpaceBetween direction="horizontal" size="xs">
                      <span>{topic.title}</span>
                      <Badge color="grey">{articles.length}</Badge>
                    </SpaceBetween>
                  </Header>
                }
              >
                <SpaceBetween size="s">
                  {articles.map((article) => (
                    <ExpandableSection
                      key={article.title}
                      headerText={article.title}
                      headerDescription={article.summary}
                      defaultExpanded={term.length > 0}
                    >
                      <SpaceBetween size="m">
                        <ol style={{ margin: '0 0 0 20px', padding: 0, lineHeight: 1.6 }}>
                          {article.steps.map((step, i) => (
                            <li key={i}>{step}</li>
                          ))}
                        </ol>
                        {article.tips && article.tips.length > 0 && (
                          <Alert type="info" header="Tips">
                            <ul style={{ margin: 0, paddingLeft: 20 }}>
                              {article.tips.map((tip, i) => (
                                <li key={i}>{tip}</li>
                              ))}
                            </ul>
                          </Alert>
                        )}
                      </SpaceBetween>
                    </ExpandableSection>
                  ))}
                </SpaceBetween>
              </Container>
            </div>
          ))
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default HelpPage;
