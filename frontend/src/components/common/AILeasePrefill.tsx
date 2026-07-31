import React, { useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import FileUpload from '@cloudscape-design/components/file-upload';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Select from '@cloudscape-design/components/select';
import Checkbox from '@cloudscape-design/components/checkbox';
import { ai } from '@/api';
import { aiUploadErrorMessage } from '@/utils/aiUpload';
import type { CamHistoryRow, CamHistoryParseResult } from '@/types';

type DocumentScope = 'active' | 'prior';

interface AILeasePrefillProps {
  /** Called with the model's suggested field map for the form to apply. */
  onSuggested: (suggested: Record<string, unknown>) => void;
  /**
   * Called with the uploaded document after a successful extraction so the
   * parent can keep it queued as an attachment when the lease is saved.
   */
  onFileExtracted?: (file: File) => void;
  /**
   * Called when historical rows are extracted from the document.
   * The parent should open CamHistoryReviewModal so the user can review and
   * import them. NOT called when the document scope is "active" unless the
   * "Also extract schedule" checkbox is ticked.
   */
  onHistoryParsed?: (
    rows: CamHistoryRow[],
    meta: CamHistoryParseResult,
    periodStatus: 'auto' | 'historical',
  ) => void;
}

const SCOPE_OPTIONS = [
  { value: 'active', label: 'This is the current / active lease' },
  { value: 'prior', label: 'This is a prior or expired lease / amendment' },
];

/**
 * AI lease-detail ingestion. Supports two modes:
 * - "Active lease" — calls parseLease for field suggestions; optionally also
 *   calls parseLeaseHistory to extract the year-by-year schedule.
 * - "Prior/expired lease" — calls ONLY parseLeaseHistory; never calls
 *   onSuggested so the active lease's fields remain untouched.
 */
const AILeasePrefill: React.FC<AILeasePrefillProps> = ({
  onSuggested,
  onFileExtracted,
  onHistoryParsed,
}) => {
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [scope, setScope] = useState<DocumentScope>('active');
  const [alsoExtractSchedule, setAlsoExtractSchedule] = useState(false);

  const run = async () => {
    if (files.length === 0) return;
    const file = files[0];
    setLoading(true);
    setError(null);
    setDone(false);
    try {
      if (scope === 'active') {
        // Extract lease fields for this form
        const res = await ai.parseLease(file);
        onSuggested(res.data.suggested || {});
        onFileExtracted?.(file);

        // Optionally also extract the year-by-year schedule
        if (alsoExtractSchedule && onHistoryParsed) {
          try {
            const histRes = await ai.parseLeaseHistory(file);
            if (histRes.data.periods.length > 0) {
              onHistoryParsed(histRes.data.periods, histRes.data, 'auto');
            }
          } catch {
            // Non-critical: schedule extraction failed silently
          }
        }
      } else {
        // Prior/expired lease — extract history ONLY, do NOT touch lease fields
        const res = await ai.parseLeaseHistory(file);
        if (onHistoryParsed && res.data.periods.length > 0) {
          onHistoryParsed(res.data.periods, res.data, 'historical');
        }
        onFileExtracted?.(file);
      }
      setDone(true);
    } catch (err: unknown) {
      setError(aiUploadErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Container
      header={
        <Header
          variant="h2"
          description="Upload a lease document and let AI pre-fill the fields below for your review."
        >
          AI assist — extract from document
        </Header>
      }
    >
      <SpaceBetween size="m">
        <Select
          selectedOption={SCOPE_OPTIONS.find((o) => o.value === scope) ?? SCOPE_OPTIONS[0]}
          onChange={({ detail }) => {
            setScope((detail.selectedOption.value as DocumentScope) ?? 'active');
            setDone(false);
          }}
          options={SCOPE_OPTIONS}
        />

        {scope === 'prior' && (
          <Alert type="info">
            When a prior or expired lease is selected, AI will extract only the year-by-year rent
            and CAM schedule for historical reference. The active lease's current financial terms
            will <strong>not</strong> be changed.
          </Alert>
        )}

        <FileUpload
          onChange={({ detail }) => {
            setFiles(detail.value);
            setDone(false);
          }}
          value={files}
          accept=".pdf,.txt,.docx,.png,.jpg,.jpeg,.tif,.tiff"
          i18nStrings={{
            uploadButtonText: () => 'Choose document',
            dropzoneText: () => 'Drop a lease document here',
            removeFileAriaLabel: (i) => `Remove file ${i + 1}`,
            limitShowFewer: 'Show fewer',
            limitShowMore: 'Show more',
            errorIconAriaLabel: 'Error',
          }}
          constraintText="PDF, image, or text. Large documents are read in sections, so they can take a little longer. The extracted values are suggestions — confirm before saving."
        />

        {scope === 'active' && onHistoryParsed && (
          <Checkbox
            checked={alsoExtractSchedule}
            onChange={({ detail }) => setAlsoExtractSchedule(detail.checked)}
          >
            Also extract the year-by-year rent / CAM schedule from this document
          </Checkbox>
        )}

        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={run} loading={loading} disabled={files.length === 0}>
            {scope === 'active' ? 'Extract details' : 'Extract schedule'}
          </Button>
        </SpaceBetween>
        {error && <Alert type="warning">{error}</Alert>}
        {done && !error && (
          <Box variant="small" color="text-status-success">
            {scope === 'active'
              ? 'Suggestions applied below, and the document will be attached when you save. Review and edit before saving.'
              : 'Historical schedule extracted. Review the rows in the panel below before importing.'}
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default AILeasePrefill;
