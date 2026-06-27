import React, { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Textarea from '@cloudscape-design/components/textarea';
import FormField from '@cloudscape-design/components/form-field';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import { ai } from '@/api';
import { useEntitlements } from '@/hooks/useEntitlements';
import type { AssistantQueryResult } from '@/types';

const SOURCE_LABELS: Record<string, string> = {
  lease: 'Lease',
  lease_document: 'Lease document',
  lease_abstract: 'Lease abstract',
  ticket: 'Maintenance ticket',
};

/**
 * AI portfolio assistant (Pro+). Answers natural-language questions about the
 * organization's leases, maintenance tickets and lease abstracts using
 * retrieval-augmented generation, returning a grounded answer plus the source
 * passages it cited. Locked with an upgrade prompt when the org lacks the
 * ``ai_assist`` entitlement, and degrades gracefully when Gemini is not
 * configured on the server.
 */
const AIPortfolioAssistant: React.FC = () => {
  const { hasFeature, loading: entLoading } = useEntitlements();
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<AssistantQueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = hasFeature('ai_assist');

  const ask = async () => {
    const trimmed = question.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    try {
      const res = await ai.assistantQuery(trimmed);
      setResult(res.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        setError('AI assist is not configured on the server. Add a Gemini API key to enable the assistant.');
      } else if (status === 402) {
        setError('The portfolio assistant requires the Pro plan or higher.');
      } else {
        setError('Failed to answer the question. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  if (entLoading) return null;

  if (!enabled) {
    return (
      <Container header={<Header variant="h2">AI portfolio assistant <Badge color="blue">Pro</Badge></Header>}>
        <Alert type="info">
          Ask natural-language questions about your leases, maintenance tickets and lease
          abstracts and get grounded answers with citations — powered by AI. Available on the
          Pro and Enterprise plans.
        </Alert>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Ask a question about your portfolio. Answers are grounded in your own leases, tickets and abstracts, with citations."
          actions={
            <Button onClick={ask} variant="primary" loading={loading} disabled={!question.trim()}>
              Ask
            </Button>
          }
        >
          AI portfolio assistant <Badge color="blue">Pro</Badge>
        </Header>
      }
    >
      <SpaceBetween size="m">
        <FormField label="Your question">
          <Textarea
            value={question}
            onChange={({ detail }) => setQuestion(detail.value)}
            placeholder="e.g. Which leases expire in the next 6 months, and what are their notice periods?"
            rows={3}
          />
        </FormField>
        {error && <Alert type="warning">{error}</Alert>}
        {result && (
          <Box>
            <Box variant="awsui-key-label">Answer</Box>
            <div style={{ paddingTop: '8px', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
              {result.answer}
            </div>
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
                          [{c.index}] {SOURCE_LABELS[c.source_type] || c.source_type}
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
    </Container>
  );
};

export default AIPortfolioAssistant;
