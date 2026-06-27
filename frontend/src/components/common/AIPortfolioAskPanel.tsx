import React, { useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import FormField from '@cloudscape-design/components/form-field';
import Textarea from '@cloudscape-design/components/textarea';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import { Link as RouterLink } from 'react-router-dom';
import DOMPurify from 'dompurify';
import { ai } from '@/api';
import { useEntitlements } from '@/hooks/useEntitlements';
import type { PortfolioAskResult } from '@/types';

const EXAMPLE_QUESTIONS = [
  'Which leases have a co-tenancy clause expiring in 2026?',
  "What's our total CAM exposure in the Northeast?",
  'Which leases allow the landlord to relocate the tenant?',
];

/**
 * "Ask your portfolio" — grounded natural-language Q&A over the organization's
 * indexed lease documents (Pro+). Reuses the existing semantic/keyword document
 * retrieval and layers an AI generation step that answers with citations back
 * to the supporting lease document passages. Locked with an upgrade prompt when
 * the org lacks ``ai_assist`` and degrades gracefully when Gemini is not
 * configured on the server.
 */
const AIPortfolioAskPanel: React.FC = () => {
  const { hasFeature, loading: entLoading } = useEntitlements();
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<PortfolioAskResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const enabled = hasFeature('ai_assist');

  const ask = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text) return;
    if (q !== undefined) setQuestion(q);
    setLoading(true);
    setError(null);
    try {
      const res = await ai.askPortfolio(text);
      setResult(res.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        setError('AI assist is not configured on the server. Add a Gemini API key to enable portfolio Q&A.');
      } else if (status === 402) {
        setError('Portfolio Q&A requires the Pro plan or higher.');
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
      <Container header={<Header variant="h2">Ask your portfolio <Badge color="blue">Pro</Badge></Header>}>
        <Alert type="info">
          Ask natural-language questions about your leases — e.g. &ldquo;which leases have a
          co-tenancy clause expiring in 2026?&rdquo; — and get grounded answers with citations back
          to the source lease documents. Available on the Pro and Enterprise plans.
        </Alert>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Ask a natural-language question about your leases and get an answer grounded in your indexed lease documents, with citations."
        >
          Ask your portfolio <Badge color="blue">Pro</Badge>
        </Header>
      }
    >
      <SpaceBetween size="m">
        <FormField
          label="Question"
          description="Answers are grounded only in lease documents that have been uploaded and indexed."
        >
          <Textarea
            value={question}
            onChange={(e) => setQuestion(e.detail.value)}
            placeholder="e.g. Which leases have a co-tenancy clause expiring in 2026?"
            rows={2}
          />
        </FormField>

        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => ask()} variant="primary" loading={loading} disabled={!question.trim()}>
            Ask
          </Button>
        </SpaceBetween>

        <Box variant="small" color="text-status-inactive">
          Try:{' '}
          {EXAMPLE_QUESTIONS.map((q, i) => (
            <React.Fragment key={q}>
              {i > 0 && ' · '}
              <Button variant="inline-link" onClick={() => ask(q)} disabled={loading}>
                {q}
              </Button>
            </React.Fragment>
          ))}
        </Box>

        {error && <Alert type="warning">{error}</Alert>}

        {result && (
          <Box>
            {!result.grounded && (
              <Alert type="info">
                No indexed lease documents matched that question. Make sure the related lease
                documents have been uploaded and indexed.
              </Alert>
            )}
            <div
              style={{ paddingTop: '8px', lineHeight: 1.5 }}
              // answer_html is server-rendered Markdown; sanitize defensively
              // against any HTML the model may have emitted before injecting it.
              dangerouslySetInnerHTML={{
                __html: DOMPurify.sanitize(result.answer_html || '', {
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

            {result.citations.length > 0 && (
              <ExpandableSection
                headerText={`Sources (${result.citations.length})`}
                variant="footer"
                defaultExpanded
              >
                <SpaceBetween size="s">
                  {result.citations.map((c) => (
                    <Box key={c.index}>
                      <Box variant="awsui-key-label">
                        [{c.index}]{' '}
                        <RouterLink to={`/leases/${c.lease_id}`}>
                          {c.lease_name || 'Untitled lease'}
                        </RouterLink>
                        {c.source_filename ? ` — ${c.source_filename}` : ''}
                      </Box>
                      <Box variant="small" color="text-body-secondary">
                        {c.snippet}
                      </Box>
                    </Box>
                  ))}
                </SpaceBetween>
              </ExpandableSection>
            )}

            <Box variant="small" color="text-status-inactive" padding={{ top: 's' }}>
              Generated by {result.model}. Review the cited passages before acting.
            </Box>
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default AIPortfolioAskPanel;
