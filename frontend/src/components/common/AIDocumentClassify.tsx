import React, { useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import FileUpload from '@cloudscape-design/components/file-upload';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import { ai as aiApi } from '@/api';
import type { DocumentClassifyResult } from '@/types';

interface AIDocumentClassifyProps {
  /** Heading shown on the container. */
  title?: string;
  /** Helper text describing what happens. */
  description?: string;
  /** Text shown inside the dropzone. */
  dropzoneText?: string;
  /**
   * Called with the uploaded file after a successful classification so the
   * parent can queue it as an attachment when the record is saved.
   */
  onFileClassified: (file: File, result: DocumentClassifyResult) => void;
}

const DOC_TYPE_LABELS: Record<DocumentClassifyResult['document_type'], string> = {
  vendor_invoice: 'Vendor invoice',
  insurance_certificate: 'Insurance certificate',
  lease_amendment: 'Lease amendment',
  lease: 'Lease',
  unknown: 'Unrecognized',
};

const CONFIDENCE_COLOR: Record<
  DocumentClassifyResult['confidence'],
  'green' | 'blue' | 'grey'
> = {
  high: 'green',
  medium: 'blue',
  low: 'grey',
};

/**
 * AI document classification for wizards that don't have a dedicated field
 * parser (e.g. the Office Wizard). Uploads a document, asks Gemini to identify
 * what it is, shows the detected type/confidence, and queues the file so it is
 * attached to the record on save. Degrades gracefully when AI is not
 * configured on the server.
 */
const AIDocumentClassify: React.FC<AIDocumentClassifyProps> = ({
  title = 'Identify a document with AI',
  description = 'Upload a document and let AI detect what it is before attaching it.',
  dropzoneText = 'Drop a document here to identify it',
  onFileClassified,
}) => {
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DocumentClassifyResult | null>(null);

  const run = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await aiApi.classifyDocument(files[0]);
      setResult(res.data);
      onFileClassified(files[0], res.data);
      // Clear the picker so the same file can be re-selected if needed and the
      // dropzone is ready for the next document.
      setFiles([]);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        setError('AI assist is not configured on the server. You can still attach documents manually.');
      } else {
        setError('Could not identify the document. You can still attach it manually.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Container header={<Header variant="h2" description={description}>{title}</Header>}>
      <SpaceBetween size="m">
        <FileUpload
          onChange={({ detail }) => {
            setFiles(detail.value);
            setResult(null);
          }}
          value={files}
          accept=".pdf,.txt,.docx,.png,.jpg,.jpeg,.tif,.tiff"
          i18nStrings={{
            uploadButtonText: () => 'Choose document',
            dropzoneText: () => dropzoneText,
            removeFileAriaLabel: (i) => `Remove file ${i + 1}`,
            limitShowFewer: 'Show fewer',
            limitShowMore: 'Show more',
            errorIconAriaLabel: 'Error',
          }}
          constraintText="PDF, image, or text. The document is added to this office once identified."
        />
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={run} loading={loading} disabled={files.length === 0}>
            Identify &amp; attach
          </Button>
        </SpaceBetween>
        {error && <Alert type="warning">{error}</Alert>}
        {result && !error && (
          <Alert type="success">
            <SpaceBetween size="xs">
              <Box>
                Detected:{' '}
                <strong>{DOC_TYPE_LABELS[result.document_type] || result.document_type}</strong>{' '}
                <Badge color={CONFIDENCE_COLOR[result.confidence]}>{result.confidence} confidence</Badge>
              </Box>
              {result.reasoning && (
                <Box variant="small" color="text-body-secondary">
                  {result.reasoning}
                </Box>
              )}
              <Box variant="small">Added to the documents queued for this office below.</Box>
            </SpaceBetween>
          </Alert>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default AIDocumentClassify;
