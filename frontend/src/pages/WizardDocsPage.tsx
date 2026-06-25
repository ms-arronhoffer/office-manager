import React from 'react';
import Box from '@cloudscape-design/components/box';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';

const STEP_TYPES = [
  {
    type: 'message',
    description: 'Displays a bot message and auto-advances to the next step after a short delay. Used for welcome messages and transitions.',
    requiredFields: 'text, next',
    example: '{ "id": "start", "type": "message", "text": "Welcome!", "next": "action_select" }',
  },
  {
    type: 'text',
    description: 'Shows a textarea for free-form user input. The response is stored in the field specified by "field". Supports optional skip.',
    requiredFields: 'text, field, next',
    example: '{ "id": "subject", "type": "text", "text": "Describe the issue:", "field": "subject", "next": "priority" }',
  },
  {
    type: 'choice',
    description: 'Displays tile-based options for the user to select one. Each option can specify a different "next" step for branching.',
    requiredFields: 'text, field, options',
    example: '{ "id": "action", "type": "choice", "text": "Pick an action:", "field": "_action", "options": [{"label": "Option A", "value": "a", "next": "step_a"}, {"label": "Option B", "value": "b", "next": "step_b"}] }',
  },
  {
    type: 'select',
    description: 'Dropdown selection. Options can be a static array or a dynamic token like "__offices__" or "__categories__".',
    requiredFields: 'text, field, options, next',
    example: '{ "id": "office", "type": "select", "text": "Pick an office:", "field": "office_id", "options": "__offices__", "next": "next_step" }',
  },
  {
    type: 'confirm',
    description: 'Shows a summary of all collected answers and a submit button. If ticket fields (subject, office_id, category_id) are present, submits a ticket. Otherwise shows a generic "Done" action.',
    requiredFields: 'text',
    example: '{ "id": "confirm", "type": "confirm", "text": "Ready to submit?" }',
  },
  {
    type: 'guidance',
    description: 'Displays an informational alert. Optionally shows follow-up text. Terminal step (no input collected). Good for help or error information.',
    requiredFields: 'text',
    example: '{ "id": "help", "type": "guidance", "text": "Contact IT for help.", "followUp": "Email: it@example.com" }',
  },
  {
    type: 'display_results',
    description: 'Fetches data from a backend API endpoint and displays it in a table. Uses URL templates with parameter interpolation from collected answers.',
    requiredFields: 'text, endpoint, params_from, columns',
    example: '{ "id": "vendors", "type": "display_results", "text": "Vendors for this office:", "endpoint": "/offices/{office_id}/vendors", "params_from": ["office_id"], "columns": [{"key": "landlord_company", "header": "Company"}] }',
  },
];

const DYNAMIC_TOKENS = [
  {
    token: '__offices__',
    description: 'Resolves to a dropdown list of all active offices. Each option has label = office location name, value = office UUID.',
    usedIn: 'select and choice step types',
  },
  {
    token: '__categories__',
    description: 'Resolves to a list of all ticket categories. Each option has label = category name, value = category UUID.',
    usedIn: 'select and choice step types',
  },
];

const AVAILABLE_ENDPOINTS = [
  { endpoint: '/offices/{office_id}/vendors', description: 'Landlords/vendors assigned to an office', params: 'office_id' },
  { endpoint: '/offices/{office_id}/hvac-contracts', description: 'HVAC contracts for an office', params: 'office_id' },
];

const EXAMPLE_CONFIG = `[
  {
    "id": "start",
    "type": "message",
    "text": "Welcome to the SwiftLease Portal!",
    "next": "action_select"
  },
  {
    "id": "action_select",
    "type": "choice",
    "text": "What would you like to do?",
    "field": "_action",
    "options": [
      { "label": "Create a Maintenance Ticket", "value": "ticket", "next": "ticket_office" },
      { "label": "Look Up Vendors for an Office", "value": "vendors", "next": "vendor_office" },
      { "label": "View HVAC Contracts for an Office", "value": "hvac", "next": "hvac_office" }
    ]
  },
  {
    "id": "ticket_office",
    "type": "select",
    "text": "Which office is this for?",
    "field": "office_id",
    "options": "__offices__",
    "next": "ticket_category"
  },
  {
    "id": "ticket_category",
    "type": "choice",
    "text": "What type of issue?",
    "field": "category_id",
    "options": "__categories__",
    "next": "ticket_subject"
  },
  {
    "id": "ticket_subject",
    "type": "text",
    "text": "Brief summary of the issue:",
    "field": "subject",
    "next": "ticket_description"
  },
  {
    "id": "ticket_description",
    "type": "text",
    "text": "Describe the issue in detail:",
    "field": "description",
    "next": "ticket_priority"
  },
  {
    "id": "ticket_priority",
    "type": "select",
    "text": "How urgent is this?",
    "field": "priority",
    "options": [
      { "label": "Low", "value": "low" },
      { "label": "Medium", "value": "medium" },
      { "label": "High", "value": "high" }
    ],
    "next": "ticket_confirm"
  },
  {
    "id": "ticket_confirm",
    "type": "confirm",
    "text": "Ready to submit your maintenance ticket?"
  },
  {
    "id": "vendor_office",
    "type": "select",
    "text": "Which office to look up vendors for?",
    "field": "office_id",
    "options": "__offices__",
    "next": "vendor_results"
  },
  {
    "id": "vendor_results",
    "type": "display_results",
    "text": "Vendors/landlords for this office:",
    "endpoint": "/offices/{office_id}/vendors",
    "params_from": ["office_id"],
    "columns": [
      { "key": "landlord_company", "header": "Company" },
      { "key": "contact_name", "header": "Contact" },
      { "key": "contact_email", "header": "Email" },
      { "key": "contact_phone", "header": "Phone" }
    ]
  },
  {
    "id": "hvac_office",
    "type": "select",
    "text": "Which office to view HVAC contracts for?",
    "field": "office_id",
    "options": "__offices__",
    "next": "hvac_results"
  },
  {
    "id": "hvac_results",
    "type": "display_results",
    "text": "HVAC contracts for this office:",
    "endpoint": "/offices/{office_id}/hvac-contracts",
    "params_from": ["office_id"],
    "columns": [
      { "key": "hvac_company", "header": "HVAC Company" },
      { "key": "contact", "header": "Contact" },
      { "key": "frequency", "header": "Frequency" },
      { "key": "next_service", "header": "Next Service" },
      { "key": "landlord_handles", "header": "Landlord Handles" }
    ]
  }
]`;

const WizardDocsPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Home', href: '/' },
              { text: 'Wizard Configs', href: '/wizard-configs' },
              { text: 'Flow Authoring Guide', href: '/wizard-docs' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Learn how to create and customize wizard flows for the Decision Portal"
          >
            Flow Authoring Guide
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        {/* Overview */}
        <Container header={<Header variant="h2">Overview</Header>}>
          <SpaceBetween size="s">
            <Box>
              The Decision Portal is powered by a <strong>wizard configuration</strong> stored as JSON.
              Each configuration defines a series of <strong>steps</strong> that the user walks through
              in a chat-like interface. Steps can collect input, display data, branch to different paths,
              or submit tickets.
            </Box>
            <Box>
              Wizard configs are managed from the <strong>Wizard Configs</strong> admin page. The
              active/default config is what users see when they visit the Decision Portal. You can
              create multiple configs and switch between them.
            </Box>
            <Alert type="info">
              The portal renders steps sequentially based on each step's <code>next</code> field.
              For branching, use <code>choice</code> steps where each option specifies a different <code>next</code> step.
            </Alert>
          </SpaceBetween>
        </Container>

        {/* Step Types Reference */}
        <Container header={<Header variant="h2">Step Types Reference</Header>}>
          <Table
            items={STEP_TYPES}
            columnDefinitions={[
              { id: 'type', header: 'Type', cell: (item) => <code>{item.type}</code>, width: 140 },
              { id: 'description', header: 'Description', cell: (item) => item.description },
              { id: 'requiredFields', header: 'Required Fields', cell: (item) => <code>{item.requiredFields}</code>, width: 220 },
            ]}
            variant="embedded"
          />
          <Box padding={{ top: 'm' }}>
            <ExpandableSection headerText="JSON examples for each step type">
              <SpaceBetween size="s">
                {STEP_TYPES.map((s) => (
                  <div key={s.type}>
                    <Box variant="awsui-key-label">{s.type}</Box>
                    <pre style={{ background: '#f2f3f3', padding: 12, borderRadius: 8, fontSize: 13, overflow: 'auto' }}>
                      {s.example}
                    </pre>
                  </div>
                ))}
              </SpaceBetween>
            </ExpandableSection>
          </Box>
        </Container>

        {/* Step Fields Reference */}
        <Container header={<Header variant="h2">Step Fields Reference</Header>}>
          <Table
            items={[
              { field: 'id', required: 'Yes', description: 'Unique identifier for the step. Used by "next" to link steps together.' },
              { field: 'type', required: 'Yes', description: 'Step type: message, text, choice, select, confirm, guidance, or display_results.' },
              { field: 'text', required: 'Yes', description: 'The message or prompt displayed to the user.' },
              { field: 'field', required: 'For input steps', description: 'The key name where the user\'s answer is stored. Use "_" prefix for internal fields (hidden from confirm summary).' },
              { field: 'options', required: 'For select/choice', description: 'Array of {label, value, next?} objects, or a dynamic token string like "__offices__".' },
              { field: 'next', required: 'Usually', description: 'ID of the next step. Not needed for terminal steps (confirm with no continuation, guidance).' },
              { field: 'optional', required: 'No', description: 'If true, text steps allow the user to type "skip" to skip the field.' },
              { field: 'followUp', required: 'No', description: 'Additional text shown below guidance steps.' },
              { field: 'endpoint', required: 'For display_results', description: 'API URL template, e.g., "/offices/{office_id}/vendors". Parameters in {braces} are interpolated from answers.' },
              { field: 'params_from', required: 'For display_results', description: 'Array of answer field names to interpolate into the endpoint URL.' },
              { field: 'columns', required: 'For display_results', description: 'Array of {key, header} objects defining what columns to show in the results table.' },
            ]}
            columnDefinitions={[
              { id: 'field', header: 'Field', cell: (item) => <code>{item.field}</code>, width: 130 },
              { id: 'required', header: 'Required', cell: (item) => item.required, width: 140 },
              { id: 'description', header: 'Description', cell: (item) => item.description },
            ]}
            variant="embedded"
          />
        </Container>

        {/* Dynamic Option Tokens */}
        <Container header={<Header variant="h2">Dynamic Option Tokens</Header>}>
          <SpaceBetween size="s">
            <Box>
              Instead of hardcoding options, you can use <strong>dynamic tokens</strong> that resolve
              to live data at runtime. Place the token string as the <code>options</code> value.
            </Box>
            <Table
              items={DYNAMIC_TOKENS}
              columnDefinitions={[
                { id: 'token', header: 'Token', cell: (item) => <code>{item.token}</code>, width: 180 },
                { id: 'description', header: 'Description', cell: (item) => item.description },
                { id: 'usedIn', header: 'Used In', cell: (item) => item.usedIn, width: 200 },
              ]}
              variant="embedded"
            />
          </SpaceBetween>
        </Container>

        {/* Branching Logic */}
        <Container header={<Header variant="h2">Branching Logic</Header>}>
          <SpaceBetween size="m">
            <Box>
              There are two ways to control step flow:
            </Box>
            <Box>
              <strong>1. Linear flow</strong> (step-level <code>next</code>): Each step has a <code>next</code> field
              pointing to the ID of the following step. This creates a straight-line sequence.
            </Box>
            <pre style={{ background: '#f2f3f3', padding: 12, borderRadius: 8, fontSize: 13 }}>
{`Step A (next: "B") --> Step B (next: "C") --> Step C`}
            </pre>
            <Box>
              <strong>2. Per-option branching</strong> (option-level <code>next</code>): In <code>choice</code> steps,
              each option can specify its own <code>next</code>. When the user selects that option,
              the flow jumps to the option's <code>next</code> step instead of the step's <code>next</code>.
            </Box>
            <pre style={{ background: '#f2f3f3', padding: 12, borderRadius: 8, fontSize: 13 }}>
{`action_select (choice)
  |-- Option: "Create Ticket"  --> next: "ticket_office"
  |-- Option: "Lookup Vendors" --> next: "vendor_office"
  |-- Option: "View HVAC"      --> next: "hvac_office"

Each branch is an independent flow that can end at its own
terminal step (confirm, guidance, or display_results).`}
            </pre>
            <Alert type="info">
              <strong>Tip:</strong> Use field names starting with <code>_</code> (underscore) for
              internal routing fields like <code>_action</code>. These are automatically hidden
              from the confirm summary.
            </Alert>
          </SpaceBetween>
        </Container>

        {/* The display_results Step */}
        <Container header={<Header variant="h2">The display_results Step</Header>}>
          <SpaceBetween size="m">
            <Box>
              The <code>display_results</code> step fetches data from a backend API endpoint and
              displays it in a table. It does not collect user input. Use it to show lookup results
              like vendors, HVAC contracts, or any data queryable by the backend.
            </Box>
            <Box variant="h4">How URL interpolation works:</Box>
            <Box>
              The <code>endpoint</code> field contains a URL template with parameter placeholders
              in curly braces. The <code>params_from</code> array lists which answer fields to
              inject. For example:
            </Box>
            <pre style={{ background: '#f2f3f3', padding: 12, borderRadius: 8, fontSize: 13 }}>
{`endpoint: "/offices/{office_id}/vendors"
params_from: ["office_id"]

If the user selected office with ID "abc-123" in a previous step,
the actual API call becomes: GET /api/v1/offices/abc-123/vendors`}
            </pre>
            <Box variant="h4">Available API endpoints for display_results:</Box>
            <Table
              items={AVAILABLE_ENDPOINTS}
              columnDefinitions={[
                { id: 'endpoint', header: 'Endpoint Template', cell: (item) => <code>{item.endpoint}</code>, width: 300 },
                { id: 'description', header: 'Description', cell: (item) => item.description },
                { id: 'params', header: 'Required Params', cell: (item) => <code>{item.params}</code>, width: 150 },
              ]}
              variant="embedded"
            />
          </SpaceBetween>
        </Container>

        {/* Database Interaction */}
        <Container header={<Header variant="h2">Database Interaction &amp; Field Mapping</Header>}>
          <SpaceBetween size="m">
            <Box>
              When the wizard collects answers and submits a ticket, the <code>field</code> names in
              your steps map directly to the maintenance ticket API. Here is how fields map to the
              database:
            </Box>
            <Table
              items={[
                { field: 'office_id', table: 'offices', description: 'UUID of the office. Use "__offices__" dynamic token to let user select.' },
                { field: 'category_id', table: 'ticket_categories', description: 'UUID of the ticket category. Use "__categories__" dynamic token.' },
                { field: 'subject', table: 'maintenance_tickets', description: 'Short summary of the issue (string).' },
                { field: 'description', table: 'maintenance_tickets', description: 'Detailed description of the issue (text).' },
                { field: 'priority', table: 'maintenance_tickets', description: 'Priority level: "low", "medium", or "high".' },
                { field: 'location_hours', table: 'maintenance_tickets', description: 'Location hours / access times (optional text).' },
              ]}
              columnDefinitions={[
                { id: 'field', header: 'Field Name', cell: (item) => <code>{item.field}</code>, width: 150 },
                { id: 'table', header: 'Database Table', cell: (item) => <code>{item.table}</code>, width: 200 },
                { id: 'description', header: 'Description', cell: (item) => item.description },
              ]}
              variant="embedded"
            />
            <Alert type="warning">
              For the confirm step to submit a ticket, the answers must include at minimum:
              <code> subject</code>, <code>office_id</code>, and <code>category_id</code>.
              If these fields are missing, the confirm step shows a generic "Done" button instead.
            </Alert>
          </SpaceBetween>
        </Container>

        {/* Full Example */}
        <Container header={<Header variant="h2">Full Example: Decision Portal Config</Header>}>
          <SpaceBetween size="s">
            <Box>
              Below is the complete JSON for the default Decision Portal wizard configuration.
              Copy this into the <strong>Steps JSON</strong> field when creating a new wizard config,
              or use it as a starting point for your own flows.
            </Box>
            <ExpandableSection headerText="View full JSON" defaultExpanded={false}>
              <pre style={{ background: '#f2f3f3', padding: 16, borderRadius: 8, fontSize: 12, overflow: 'auto', maxHeight: 600 }}>
                {EXAMPLE_CONFIG}
              </pre>
            </ExpandableSection>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default WizardDocsPage;
