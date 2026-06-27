import React, { useEffect, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Link from '@cloudscape-design/components/link';
import { ai } from '@/api';
import type { SimilarTicketMatch, TicketTriageSuggestion } from '@/types';

interface AITicketAssistProps {
  subject: string;
  description: string;
  /** Ticket id to exclude from duplicate detection (when editing). */
  excludeId?: string;
  /** Apply the model's category/priority/vendor suggestion to the form. */
  onApply: (suggestion: TicketTriageSuggestion) => void;
}

/**
 * AI-assist for maintenance tickets (Pro+ ``ai_assist``). On demand it asks
 * Gemini to triage the request — suggesting a category, priority, and vendor —
 * and surfaces similar open tickets to catch duplicates before submission. All
 * output is a suggestion for human review; nothing is applied without the user
 * clicking "Suggest". Degrades gracefully when AI is unconfigured or the plan
 * does not include the feature.
 */
const AITicketAssist: React.FC<AITicketAssistProps> = ({
  subject,
  description,
  excludeId,
  onApply,
}) => {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  const [matches, setMatches] = useState<SimilarTicketMatch[] | null>(null);

  useEffect(() => {
    let active = true;
    ai.status()
      .then((res) => {
        if (active) setConfigured(res.data.configured);
      })
      .catch(() => {
        if (active) setConfigured(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const run = async () => {
    if (!subject.trim()) return;
    setLoading(true);
    setError(null);
    setReasoning(null);
    setApplied(false);
    setMatches(null);
    try {
      const [triageRes, similarRes] = await Promise.all([
        ai.triageTicket(subject.trim(), description.trim()),
        ai.similarTickets(subject.trim(), description.trim(), excludeId ?? null),
      ]);
      onApply(triageRes.data.suggested);
      setReasoning(triageRes.data.suggested.reasoning ?? null);
      setApplied(true);
      setMatches(similarRes.data.matches);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        setError('AI assist is not configured on the server. Add a Gemini API key to enable this.');
      } else if (status === 402) {
        setError('AI ticket triage is a Pro feature. Upgrade your plan to enable it.');
      } else {
        setError('Could not analyse this ticket. Please fill in the fields manually.');
      }
    } finally {
      setLoading(false);
    }
  };

  // Hide entirely while we don't yet know status, or when AI is unconfigured.
  if (configured !== true) return null;

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Let AI suggest a category, priority, and vendor, and flag possible duplicate tickets."
        >
          AI assist — triage this ticket
        </Header>
      }
    >
      <SpaceBetween size="s">
        <Box>
          <Button onClick={run} loading={loading} disabled={!subject.trim()}>
            Suggest category, priority &amp; vendor
          </Button>
        </Box>
        {error && (
          <Alert type="warning" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        {applied && (
          <Alert type="success" dismissible onDismiss={() => setApplied(false)}>
            Suggestions applied below — please review before saving.
            {reasoning ? ` ${reasoning}` : ''}
          </Alert>
        )}
        {matches && matches.length > 0 && (
          <Alert type="info" header="Possible duplicate tickets">
            <SpaceBetween size="xxs">
              {matches.map((m) => (
                <Box key={m.id}>
                  <Link href={`/maintenance-tickets/${m.id}`} external>
                    {m.subject}
                  </Link>{' '}
                  <Box variant="span" color="text-status-inactive" display="inline">
                    ({m.status})
                  </Box>
                </Box>
              ))}
            </SpaceBetween>
          </Alert>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default AITicketAssist;
