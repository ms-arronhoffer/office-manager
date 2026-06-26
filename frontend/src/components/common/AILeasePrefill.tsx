import React, { useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import FileUpload from '@cloudscape-design/components/file-upload';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import { ai } from '@/api';

interface AILeasePrefillProps {
  /** Called with the model's suggested field map for the form to apply. */
  onSuggested: (suggested: Record<string, unknown>) => void;
  /**
   * Called with the uploaded document after a successful extraction so the
   * parent can keep it queued as an attachment when the lease is saved.
   */
  onFileExtracted?: (file: File) => void;
}

/**
 * Basic AI lease-detail ingestion (available on all plans). Uploads a lease
 * document, asks Gemini to extract key fields, and hands the suggestions back to
 * the form for human review before saving. Degrades gracefully when the server
 * has no Gemini API key configured.
 */
const AILeasePrefill: React.FC<AILeasePrefillProps> = ({ onSuggested, onFileExtracted }) => {
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const run = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);
    setDone(false);
    try {
      const res = await ai.parseLease(files[0]);
      onSuggested(res.data.suggested || {});
      // Keep the parsed document attached to the lease once it's created so the
      // user doesn't have to re-upload the file they just analysed.
      onFileExtracted?.(files[0]);
      setDone(true);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        setError('AI assist is not configured on the server. Add a Gemini API key to enable this.');
      } else {
        setError('Could not read the document. Please enter the details manually.');
      }
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
        <FileUpload
          onChange={({ detail }) => {
            setFiles(detail.value);
            setDone(false);
          }}
          value={files}
          accept=".pdf,.txt,.png,.jpg,.jpeg,.tif,.tiff"
          i18nStrings={{
            uploadButtonText: () => 'Choose document',
            dropzoneText: () => 'Drop a lease document here',
            removeFileAriaLabel: (i) => `Remove file ${i + 1}`,
            limitShowFewer: 'Show fewer',
            limitShowMore: 'Show more',
            errorIconAriaLabel: 'Error',
          }}
          constraintText="PDF, image, or text. The extracted values are suggestions — confirm before saving."
        />
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={run} loading={loading} disabled={files.length === 0}>
            Extract details
          </Button>
        </SpaceBetween>
        {error && <Alert type="warning">{error}</Alert>}
        {done && !error && (
          <Box variant="small" color="text-status-success">
            Suggestions applied below, and the document will be attached when you save. Review and edit before saving.
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default AILeasePrefill;
