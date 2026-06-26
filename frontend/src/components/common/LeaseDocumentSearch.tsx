import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Input from '@cloudscape-design/components/input';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Grid from '@cloudscape-design/components/grid';
import Spinner from '@cloudscape-design/components/spinner';
import { ai } from '@/api';
import type { LeaseDocumentSearchMatch, LeaseDocumentTextResult } from '@/types';

interface Props {
  leaseId: string;
  canEdit?: boolean;
}

/** Split a query into distinct, lowercased, non-empty terms for highlighting. */
const queryTerms = (query: string): string[] => {
  const seen = new Set<string>();
  for (const raw of query.toLowerCase().split(/\s+/)) {
    const term = raw.trim();
    if (term) seen.add(term);
  }
  return Array.from(seen);
};

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Render `text` with every occurrence of any query term wrapped in a <mark>.
 *
 * Each highlighted occurrence is registered with `registerMark` so the caller
 * can scroll between matches. The match at `activeOccurrence` is styled
 * distinctly so the user can see which occurrence is currently selected.
 */
const highlightText = (
  text: string,
  terms: string[],
  activeOccurrence: number,
  registerMark: (index: number, el: HTMLElement | null) => void,
): { nodes: React.ReactNode[]; count: number } => {
  if (!terms.length || !text) {
    return { nodes: [text], count: 0 };
  }
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join('|')})`, 'gi');
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let occurrence = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const current = occurrence;
    const isActive = current === activeOccurrence;
    nodes.push(
      <mark
        key={`m-${current}`}
        ref={(el) => registerMark(current, el)}
        style={{
          backgroundColor: isActive ? '#ffd54f' : '#fff3bf',
          padding: '0 1px',
          borderRadius: '2px',
          outline: isActive ? '2px solid #f59f00' : 'none',
        }}
      >
        {match[0]}
      </mark>,
    );
    lastIndex = match.index + match[0].length;
    occurrence += 1;
    // Guard against zero-length matches (shouldn't happen with these terms).
    if (match.index === pattern.lastIndex) pattern.lastIndex += 1;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return { nodes, count: occurrence };
};

/**
 * Keyword / semantic search over the text of documents attached to a lease.
 *
 * Results are shown in a master/detail layout: the left pane lists each match
 * (file name, Keyword/Semantic badge, snippet) and selecting one drives a
 * preview pane on the right that renders the full extracted document text with
 * every occurrence of the query terms highlighted and Previous/Next navigation.
 * Admins/editors can trigger a (re)index of existing attachments via "Rebuild
 * index".
 */
const LeaseDocumentSearch: React.FC<Props> = ({ leaseId, canEdit }) => {
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [matches, setMatches] = useState<LeaseDocumentSearchMatch[] | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [preview, setPreview] = useState<LeaseDocumentTextResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [activeOccurrence, setActiveOccurrence] = useState(0);

  const markRefs = useRef<(HTMLElement | null)[]>([]);
  const registerMark = useCallback((index: number, el: HTMLElement | null) => {
    markRefs.current[index] = el;
  }, []);

  const terms = useMemo(() => queryTerms(submittedQuery), [submittedQuery]);

  const runSearch = async () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setInfo(null);
    setPreview(null);
    setPreviewError(null);
    try {
      const res = await ai.searchLeaseDocuments(leaseId, trimmed);
      setMatches(res.data.matches);
      setSubmittedQuery(trimmed);
      setSelectedIndex(res.data.matches.length > 0 ? 0 : null);
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

  const selectedMatch =
    selectedIndex !== null && matches ? matches[selectedIndex] ?? null : null;
  const selectedAttachmentId = selectedMatch?.attachment_id ?? null;

  // Load the preview document text whenever the selected match changes.
  useEffect(() => {
    if (!selectedAttachmentId) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewError(null);
    setActiveOccurrence(0);
    markRefs.current = [];
    ai
      .getLeaseDocumentText(leaseId, selectedAttachmentId)
      .then((res) => {
        if (!cancelled) setPreview(res.data);
      })
      .catch(() => {
        if (!cancelled) setPreviewError('Could not load the document preview.');
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [leaseId, selectedAttachmentId]);

  const previewText = preview?.text ?? '';
  const { nodes: previewNodes, count: occurrenceCount } = useMemo(
    () => highlightText(previewText, terms, activeOccurrence, registerMark),
    [previewText, terms, activeOccurrence, registerMark],
  );

  // Scroll the active occurrence into view when it changes.
  useEffect(() => {
    const el = markRefs.current[activeOccurrence];
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [activeOccurrence, previewText]);

  const goToMatch = (delta: number) => {
    if (occurrenceCount === 0) return;
    setActiveOccurrence((prev) => (prev + delta + occurrenceCount) % occurrenceCount);
  };

  const downloadUrl = selectedAttachmentId
    ? `/api/v1/attachments/${selectedAttachmentId}/download`
    : undefined;

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
          <Grid
            gridDefinition={[
              { colspan: { default: 12, m: 5 } },
              { colspan: { default: 12, m: 7 } },
            ]}
          >
            {/* Left pane — matches list */}
            <Box>
              <SpaceBetween size="xs">
                <Box variant="awsui-key-label">
                  {matches.length} match{matches.length === 1 ? '' : 'es'}
                </Box>
                {matches.map((m, i) => {
                  const isSelected = i === selectedIndex;
                  return (
                    <div
                      key={`${m.attachment_id ?? 'na'}-${m.chunk_index ?? i}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedIndex(i)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          setSelectedIndex(i);
                        }
                      }}
                      style={{
                        cursor: 'pointer',
                        borderLeft: `3px solid ${isSelected ? '#0972d3' : 'transparent'}`,
                        background: isSelected ? '#f0f7ff' : 'transparent',
                        padding: '8px 10px',
                        borderRadius: '4px',
                      }}
                    >
                      <SpaceBetween direction="horizontal" size="xs">
                        <Box variant="strong">{m.source_filename}</Box>
                        <Badge color={m.match_type === 'semantic' ? 'green' : 'blue'}>
                          {m.match_type === 'semantic' ? 'Semantic' : 'Keyword'}
                        </Badge>
                      </SpaceBetween>
                      <Box variant="small" color="text-body-secondary">
                        {m.snippet}
                      </Box>
                    </div>
                  );
                })}
              </SpaceBetween>
            </Box>

            {/* Right pane — document preview */}
            <Box>
              <SpaceBetween size="xs">
                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                  <Box variant="strong">{selectedMatch?.source_filename ?? 'Preview'}</Box>
                  {occurrenceCount > 0 && (
                    <>
                      <Box variant="small" color="text-body-secondary">
                        {activeOccurrence + 1} of {occurrenceCount}
                      </Box>
                      <Button
                        iconName="angle-up"
                        variant="icon"
                        ariaLabel="Previous match"
                        onClick={() => goToMatch(-1)}
                      />
                      <Button
                        iconName="angle-down"
                        variant="icon"
                        ariaLabel="Next match"
                        onClick={() => goToMatch(1)}
                      />
                    </>
                  )}
                  {downloadUrl && (
                    <Button
                      iconName="external"
                      href={downloadUrl}
                      target="_blank"
                      iconAlign="right"
                    >
                      Open original
                    </Button>
                  )}
                </SpaceBetween>

                {previewLoading && (
                  <Box padding="s">
                    <Spinner /> Loading preview…
                  </Box>
                )}
                {previewError && <Alert type="error">{previewError}</Alert>}

                {!previewLoading && !previewError && preview && !preview.extractable && (
                  <Box color="text-status-inactive">
                    This document type can't be previewed as text. Use “Open original” to view it.
                  </Box>
                )}

                {!previewLoading && !previewError && preview?.extractable && (
                  <div
                    style={{
                      maxHeight: '460px',
                      overflowY: 'auto',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      fontSize: '13px',
                      lineHeight: 1.5,
                      border: '1px solid #e9ebed',
                      borderRadius: '4px',
                      padding: '12px',
                    }}
                  >
                    {previewNodes}
                  </div>
                )}
              </SpaceBetween>
            </Box>
          </Grid>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default LeaseDocumentSearch;
