import React, { useState, useRef } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import { imports as importsApi } from '@/api';

interface ImportModalProps {
  visible: boolean;
  onDismiss: () => void;
  entityName: string;
  entityLabel: string;
  onComplete?: () => void;
}

interface ImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

const ImportModal: React.FC<ImportModalProps> = ({
  visible,
  onDismiss,
  entityName,
  entityLabel,
  onComplete,
}) => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDownloadTemplate = async () => {
    setDownloading(true);
    try {
      const res = await importsApi.downloadTemplate(entityName);
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${entityName}_template.xlsx`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      setError('Failed to download template.');
    } finally {
      setDownloading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      if (!selected.name.toLowerCase().endsWith('.xlsx')) {
        setError('Please select an XLSX file.');
        return;
      }
      setFile(selected);
      setError(null);
      setResult(null);
    }
  };

  const handleImport = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const res = await importsApi.upload(entityName, file);
      setResult(res.data);
      if (onComplete) onComplete();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Import failed. Please check your file format.';
      setError(message);
    } finally {
      setUploading(false);
    }
  };

  const handleClose = () => {
    setFile(null);
    setResult(null);
    setError(null);
    onDismiss();
  };

  return (
    <Modal
      visible={visible}
      onDismiss={handleClose}
      header={`Import ${entityLabel}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={handleClose}>Close</Button>
            <Button
              variant="primary"
              loading={uploading}
              disabled={!file || uploading}
              onClick={handleImport}
            >
              Import
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="l">
        <SpaceBetween size="xs">
          <Box variant="p">
            Download the template, fill in your data, then upload the completed file. Existing
            records will be updated and new records will be created.
          </Box>
          <Box variant="small" color="text-body-secondary">
            Row 2 in the template is an example row — it will be skipped during import.
          </Box>
        </SpaceBetween>

        <Button
          iconName="download"
          loading={downloading}
          onClick={handleDownloadTemplate}
        >
          Download Template
        </Button>

        <div>
          <Box variant="awsui-key-label" margin={{ bottom: 'xxs' }}>Upload File</Box>
          <SpaceBetween direction="horizontal" size="xs">
            <Button
              iconName="upload"
              onClick={() => fileInputRef.current?.click()}
            >
              Choose File
            </Button>
            <Box variant="p" padding={{ top: 'xxs' }}>
              {file ? file.name : 'No file selected'}
            </Box>
          </SpaceBetween>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
        </div>

        {uploading && (
          <ProgressBar
            status="in-progress"
            label="Importing..."
          />
        )}

        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        {result && (
          <Alert type={result.errors.length > 0 ? 'warning' : 'success'}>
            <SpaceBetween size="xs">
              <Box>
                <strong>Created:</strong> {result.created} &nbsp;|&nbsp;
                <strong>Updated:</strong> {result.updated} &nbsp;|&nbsp;
                <strong>Skipped:</strong> {result.skipped}
              </Box>
              {result.errors.length > 0 && (
                <div>
                  <Box variant="awsui-key-label">Errors ({result.errors.length})</Box>
                  <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                    {result.errors.slice(0, 20).map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                    {result.errors.length > 20 && (
                      <li>...and {result.errors.length - 20} more</li>
                    )}
                  </ul>
                </div>
              )}
            </SpaceBetween>
          </Alert>
        )}
      </SpaceBetween>
    </Modal>
  );
};

export default ImportModal;
