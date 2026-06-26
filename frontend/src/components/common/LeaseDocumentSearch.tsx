import React, { useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Input from '@cloudscape-design/components/input';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import { ai } from '@/api';
import type { LeaseDocumentSearchMatch } from '@/types';

interface Props {
  leaseId: string;
  canEdit?: boolean;
}

/**
 * Keyword / semantic search over the text of documents attached to a lease.
 *
 * Uses embedding-based semantic ranking when AI is configured on the server,
 * otherwise falls back to keyword matching (handled server-side). Admins/editors
 * can trigger a (re)index of existing attachments via "Rebuild index".
 */
const LeaseDocumentSearch: React.FC<Props> = ({ leaseId, canEdit }) => {
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<LeaseDocumentSearchMatch[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const runSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const res = await ai.searchLeaseDocuments(leaseId, query.trim());
      setMatches(res.data.matches);
    } catch {
      setError('Document search failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const reindex = async () => {
    setReindexing(true);
    setError(null);
    setInfo(null);
    try {
      const res = await ai.reindexLeaseDocuments(leaseId);
      setInfo(`Indexed ${res.data.chunks_indexed} text chunk(s) from this lease's documents.`);
    } catch {
      setError('Failed to rebuild the document index.');
    } finally {
      setReindexing(false);
    }
  };

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Search the text inside this lease's uploaded documents (PDF, DOCX, TXT)."
          actions={
            canEdit ? (
              <Button onClick={reindex} loading={reindexing} iconName="refresh">
                Rebuild index
              </Button>
            ) : undefined
          }
        >
          Document Search
        </Header>
      }
    >
      <SpaceBetween size="m">
        <SpaceBetween direction="horizontal" size="xs">
          <Input
            value={query}
            onChange={({ detail }) => setQuery(detail.value)}
            onKeyDown={({ detail }) => {
              if (detail.key === 'Enter') runSearch();
            }}
            placeholder="e.g. renewal option, indemnification, base rent"
            type="search"
          />
          <Button variant="primary" onClick={runSearch} loading={loading} disabled={!query.trim()}>
            Search
          </Button>
        </SpaceBetween>

        {error && <Alert type="error">{error}</Alert>}
        {info && <Alert type="success">{info}</Alert>}

        {matches && matches.length === 0 && (
          <Box color="text-status-inactive">
            No matching text found in this lease's documents. If documents were uploaded
            before search was enabled, use "Rebuild index".
          </Box>
        )}

        {matches && matches.length > 0 && (
          <SpaceBetween size="s">
            {matches.map((m, i) => (
              <Box key={`${m.attachment_id ?? 'na'}-${i}`} padding={{ vertical: 'xs' }}>
                <SpaceBetween direction="horizontal" size="xs">
                  <Box variant="strong">{m.source_filename}</Box>
                  <Badge color={m.match_type === 'semantic' ? 'green' : 'blue'}>
                    {m.match_type === 'semantic' ? 'Semantic' : 'Keyword'}
                  </Badge>
                </SpaceBetween>
                <Box variant="p" color="text-body-secondary">
                  {m.snippet}
                </Box>
              </Box>
            ))}
          </SpaceBetween>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default LeaseDocumentSearch;
