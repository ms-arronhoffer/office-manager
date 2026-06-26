import React, { useEffect, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Select from '@cloudscape-design/components/select';
import FormField from '@cloudscape-design/components/form-field';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import DOMPurify from 'dompurify';
import { ai } from '@/api';
import { useEntitlements } from '@/hooks/useEntitlements';
import type { AISummaryResult } from '@/types';

const PERIODS = [
  { label: 'Weekly briefing', value: 'weekly' },
  { label: 'Monthly briefing', value: 'monthly' },
];

/**
 * AI-generated operations briefing (Pro+). Summarizes upcoming lease
 * notice/notification deadlines, expirations and maintenance load into a
 * written narrative. Locked with an upgrade prompt when the org lacks the
 * ``ai_assist`` entitlement, and degrades gracefully when Gemini is not
 * configured on the server.
 */
const AISummaryPanel: React.FC = () => {
  const { hasFeature, loading: entLoading } = useEntitlements();
  const [period, setPeriod] = useState<'weekly' | 'monthly'>('weekly');
  const [result, setResult] = useState<AISummaryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<'pdf' | 'docx' | null>(null);

  const enabled = hasFeature('ai_assist');

  useEffect(() => {
    setResult(null);
    setError(null);
  }, [period]);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await ai.summary(period);
      setResult(res.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        setError('AI assist is not configured on the server. Add a Gemini API key to enable summaries.');
      } else if (status === 402) {
        setError('AI summaries require the Pro plan or higher.');
      } else {
        setError('Failed to generate the AI summary. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const download = async (format: 'pdf' | 'docx') => {
    if (!result) return;
    setExporting(format);
    setError(null);
    try {
      const res = await ai.exportSummary(result.narrative, result.period_label, format);
      const blob = res.data as Blob;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const safe = result.period_label.replace(/[^a-zA-Z0-9-_]+/g, '_').replace(/^_+|_+$/g, '') || 'briefing';
      link.download = `${safe}.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      setError(`Failed to download the ${format.toUpperCase()} briefing. Please try again.`);
    } finally {
      setExporting(null);
    }
  };

  if (entLoading) return null;

  if (!enabled) {
    return (
      <Container header={<Header variant="h2">AI briefing <Badge color="blue">Pro</Badge></Header>}>
        <Alert type="info">
          Generate written weekly and monthly briefings of upcoming lease notice deadlines,
          expirations and maintenance — powered by AI. Available on the Pro and Enterprise plans.
        </Alert>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="AI-written summary of upcoming notice deadlines, expirations and maintenance load."
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={generate} variant="primary" loading={loading}>
                Generate
              </Button>
            </SpaceBetween>
          }
        >
          AI briefing <Badge color="blue">Pro</Badge>
        </Header>
      }
    >
      <SpaceBetween size="m">
        <FormField label="Period">
          <Select
            selectedOption={PERIODS.find((p) => p.value === period) || PERIODS[0]}
            onChange={(e) => setPeriod(e.detail.selectedOption.value as 'weekly' | 'monthly')}
            options={PERIODS}
          />
        </FormField>
        {error && <Alert type="warning">{error}</Alert>}
        {result && (
          <Box>
            <Box variant="awsui-key-label">{result.period_label}</Box>
            <div
              style={{ paddingTop: '8px', lineHeight: 1.5 }}
              // narrative_html is server-rendered Markdown; sanitize defensively
              // against any HTML the model may have emitted before injecting it.
              dangerouslySetInnerHTML={{
                __html: DOMPurify.sanitize(result.narrative_html || '', {
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
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                iconName="download"
                loading={exporting === 'pdf'}
                disabled={exporting !== null}
                onClick={() => download('pdf')}
              >
                Download PDF
              </Button>
              <Button
                iconName="download"
                loading={exporting === 'docx'}
                disabled={exporting !== null}
                onClick={() => download('docx')}
              >
                Download DOCX
              </Button>
            </SpaceBetween>
            <Box variant="small" color="text-status-inactive" padding={{ top: 's' }}>
              Generated by {result.model}. Review before acting.
            </Box>
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default AISummaryPanel;
