import React, { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Textarea from '@cloudscape-design/components/textarea';
import FormField from '@cloudscape-design/components/form-field';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import SegmentedControl from '@cloudscape-design/components/segmented-control';
import Table from '@cloudscape-design/components/table';
import DOMPurify from 'dompurify';
import { ai } from '@/api';
import { useEntitlements } from '@/hooks/useEntitlements';
import type { AssistantQueryResult, DataQueryResult } from '@/types';

const SOURCE_LABELS: Record<string, string> = {
  lease: 'Lease',
  lease_document: 'Lease document',
  lease_abstract: 'Lease abstract',
  ticket: 'Maintenance ticket',
  office: 'Office',
  landlord: 'Landlord',
  vendor: 'Vendor',
  management_company: 'Management company',
  hvac_contract: 'HVAC contract',
  office_transition: 'Office transition',
  insurance_certificate: 'Insurance certificate',
  portfolio_summary: 'Portfolio summary',
  rental_unit: 'Rental unit',
  resident: 'Resident',
  resident_lease: 'Resident lease',
  rent_charge: 'Rent charge',
  owner: 'Property owner',
  owner_distribution: 'Owner distribution',
  vendor_bill: 'Vendor bill',
  customer_invoice: 'Customer invoice',
  bank_account: 'Bank account',
  budget: 'Budget',
  inspection: 'Inspection',
  listing: 'Vacancy listing',
  rental_application: 'Rental application',
  screening_report: 'Screening report',
};

/**
 * Humanize an unrecognized source type (a raw table name emitted by the generic
 * catch-all indexer, e.g. ``gl_accounts``) into a readable label
 * (``Gl accounts``) so citations for any indexed table still read cleanly.
 */
function sourceLabel(sourceType: string): string {
  if (SOURCE_LABELS[sourceType]) return SOURCE_LABELS[sourceType];
  const words = sourceType.replace(/_/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : sourceType;
}

/**
 * AI portfolio assistant (Pro+). Answers natural-language questions across the
 * whole organization — offices, leases, lease documents, residents, owners,
 * finances and, via a generic catch-all indexer, any other organization-scoped
 * data in the database — using retrieval-augmented generation, returning a
 * grounded answer plus the source passages it cited.
 * Rendered as the content of a global, expandable side drawer (see
 * {@link AppNavigation}) so it is reachable from every view. Locked with an
 * upgrade prompt when the org lacks the ``ai_assist`` entitlement, and degrades
 * gracefully when Gemini is not configured on the server.
 */
const AIPortfolioAssistant: React.FC = () => {
  const { hasFeature, loading: entLoading } = useEntitlements();
  const [mode, setMode] = useState<'answer' | 'data'>('answer');
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<AssistantQueryResult | null>(null);
  const [dataResult, setDataResult] = useState<DataQueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = hasFeature('ai_assist');

  const describeError = (err: unknown): string => {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 503) {
      return 'AI assist is not configured on the server. Add a Gemini API key to enable the assistant.';
    }
    if (status === 402) {
      return 'The portfolio assistant requires the Pro plan or higher.';
    }
    if (status === 422) {
      return "I couldn't map that to your data. Try rephrasing with a specific record type or field.";
    }
    return 'Failed to answer the question. Please try again.';
  };

  const ask = async () => {
    const trimmed = question.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    try {
      if (mode === 'data') {
        setResult(null);
        const res = await ai.dataQuery(trimmed);
        setDataResult(res.data);
      } else {
        setDataResult(null);
        const res = await ai.assistantQuery(trimmed);
        setResult(res.data);
      }
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  };

  if (entLoading) return null;

  const header = (
    <Header variant="h2">
      AI portfolio assistant <Badge color="blue">Pro</Badge>
    </Header>
  );

  if (!enabled) {
    return (
      <div style={{ padding: '20px' }}>
        <SpaceBetween size="m">
          {header}
          <Alert type="info">
            Ask natural-language questions about anything in your portfolio — offices,
            leases, lease documents, landlords, vendors, maintenance tickets and more — and
            get grounded answers with citations — powered by AI. Available on the Pro and
            Enterprise plans.
          </Alert>
        </SpaceBetween>
      </div>
    );
  }

  return (
    <div style={{ padding: '20px' }}>
      <SpaceBetween size="m">
        <Header
          variant="h2"
          description="Ask a question about anything in your portfolio — offices, leases, landlords, vendors, tickets and more. Answers are grounded in your own data, with citations."
        >
          AI portfolio assistant <Badge color="blue">Pro</Badge>
        </Header>
        <FormField label="Mode">
          <SegmentedControl
            selectedId={mode}
            onChange={({ detail }) => setMode(detail.selectedId as 'answer' | 'data')}
            options={[
              { id: 'answer', text: 'Grounded answer' },
              { id: 'data', text: 'Data query' },
            ]}
          />
        </FormField>
        <FormField
          label="Your question"
          description={
            mode === 'data'
              ? 'Get precise counts, totals, and filtered lists from any table — e.g. "how many open residential applications" or "total rent charged by status".'
              : 'Ask anything about your portfolio; answers are grounded in your own data with citations.'
          }
        >
          <Textarea
            value={question}
            onChange={({ detail }) => setQuestion(detail.value)}
            placeholder={
              mode === 'data'
                ? 'e.g. How many vendors are in Texas? Total rent charged this month?'
                : 'e.g. Which leases expire in the next 6 months, and what are their notice periods?'
            }
            rows={3}
          />
        </FormField>
        <Button onClick={ask} variant="primary" loading={loading} disabled={!question.trim()}>
          Ask
        </Button>
        {error && <Alert type="warning">{error}</Alert>}
        {dataResult && mode === 'data' && (
          <Box>
            <Box variant="awsui-key-label">Answer</Box>
            <div style={{ paddingTop: '8px', lineHeight: 1.5 }}>{dataResult.answer}</div>
            {dataResult.rows.length > 0 && (
              <Box padding={{ top: 'm' }}>
                <Table
                  variant="embedded"
                  columnDefinitions={dataResult.columns.map((col, i) => ({
                    id: col,
                    header: col.replace(/_/g, ' '),
                    cell: (row: Array<string | number | boolean | null>) => {
                      const v = row[i];
                      return v === null || v === undefined ? '' : String(v);
                    },
                  }))}
                  items={dataResult.rows}
                  empty="No matching records."
                />
              </Box>
            )}
            <Box variant="small" color="text-status-inactive" padding={{ top: 's' }}>
              {dataResult.rows.length < dataResult.total
                ? `Showing ${dataResult.rows.length} of ${dataResult.total} matching records. `
                : ''}
              Answered from your data via a validated query (no free-form SQL). Review before acting.
            </Box>
          </Box>
        )}
        {result && mode === 'answer' && (
          <Box>
            <Box variant="awsui-key-label">Answer</Box>
            {result.answer_html ? (
              <div
                style={{ paddingTop: '8px', lineHeight: 1.5 }}
                // answer_html is server-rendered Markdown; sanitize defensively
                // against any HTML the model may have emitted before injecting it.
                dangerouslySetInnerHTML={{
                  __html: DOMPurify.sanitize(result.answer_html, {
                    ALLOWED_TAGS: [
                      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                      'p', 'br', 'hr',
                      'ul', 'ol', 'li',
                      'strong', 'em', 'b', 'i', 'code', 'pre', 'blockquote',
                      'table', 'thead', 'tbody', 'tr', 'th', 'td',
                    ],
                    ALLOWED_ATTR: [],
                  }),
                }}
              />
            ) : (
              // Fallback to the raw answer text when the server did not provide
              // rendered HTML, so the answer is never blank.
              <div style={{ paddingTop: '8px', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                {result.answer}
              </div>
            )}
            {result.citations.length > 0 && (
              <Box padding={{ top: 'm' }}>
                <ExpandableSection
                  headerText={`Sources (${result.citations.length})`}
                  variant="footer"
                >
                  <SpaceBetween size="s">
                    {result.citations.map((c) => (
                      <Box key={c.index}>
                        <Box variant="awsui-key-label">
                          [{c.index}] {sourceLabel(c.source_type)}
                          {c.reference ? (
                            <>
                              {' — '}
                              <RouterLink to={`/${c.reference}`}>{c.title}</RouterLink>
                            </>
                          ) : (
                            <>{' — '}{c.title}</>
                          )}
                        </Box>
                        <Box variant="small" color="text-body-secondary">
                          {c.snippet}
                        </Box>
                      </Box>
                    ))}
                  </SpaceBetween>
                </ExpandableSection>
              </Box>
            )}
            <Box variant="small" color="text-status-inactive" padding={{ top: 's' }}>
              Generated by {result.model} ({result.mode} retrieval). Review before acting.
            </Box>
          </Box>
        )}
      </SpaceBetween>
    </div>
  );
};

export default AIPortfolioAssistant;
