import React, { useEffect, useState, useCallback, useMemo } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Icon from '@cloudscape-design/components/icon';
import FileUpload from '@cloudscape-design/components/file-upload';
import Modal from '@cloudscape-design/components/modal';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import { attachments as attachmentsApi, type UploadLimits } from '@/api';
import type { Attachment } from '@/types';

interface AttachmentsPanelProps {
  entityType: string;
  entityId: string;
  canEdit: boolean;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isImageContentType(ct: string): boolean {
  return ct.startsWith('image/');
}

const AttachmentsPanel: React.FC<AttachmentsPanelProps> = ({
  entityType,
  entityId,
  canEdit,
}) => {
  const [items, setItems] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [description, setDescription] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewName, setPreviewName] = useState<string>('');

  // Guard against being rendered without an entityId.
  const hasValidEntity = Boolean(entityType && entityId);

  const fetchAttachments = useCallback(async () => {
    if (!hasValidEntity) {
      setLoading(false);
      return;
    }
    try {
      const res = await attachmentsApi.list(entityType, entityId);
      setItems(res.data);
    } catch {
      setError('Failed to load attachments.');
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId, hasValidEntity]);

  useEffect(() => {
    fetchAttachments();
  }, [fetchAttachments]);

  // Load upload limits once for client-side validation.
  useEffect(() => {
    let cancelled = false;
    attachmentsApi
      .getLimits()
      .then((res) => {
        if (!cancelled) setLimits(res.data);
      })
      .catch(() => {
        // Non-fatal; client-side validation will be skipped.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Clean up object URLs created for previews.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const validateFile = useCallback(
    (file: File): string | null => {
      if (!limits) return null;
      if (file.size > limits.max_file_size_bytes) {
        return `File is too large (${formatFileSize(file.size)}). Maximum is ${limits.max_file_size_mb} MB.`;
      }
      const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
      if (!limits.allowed_extensions.includes(ext)) {
        return `File type "${ext}" is not allowed. Allowed: ${limits.allowed_extensions.join(', ')}.`;
      }
      return null;
    },
    [limits],
  );

  const acceptAttribute = useMemo(() => {
    if (!limits) return undefined;
    return limits.allowed_extensions.join(',');
  }, [limits]);

  const pickFile = (file: File | null) => {
    setError(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile || !hasValidEntity) return;
    setUploading(true);
    setUploadProgress(0);
    setError(null);
    try {
      await attachmentsApi.upload(
        entityType,
        entityId,
        selectedFile,
        description || undefined,
        (loaded, total) => setUploadProgress(Math.round((loaded / total) * 100)),
      );
      setSelectedFile(null);
      setDescription('');
      await fetchAttachments();
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(msg || 'Failed to upload file.');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleDownload = async (attachment: Attachment) => {
    try {
      const res = await attachmentsApi.download(attachment.id);
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = attachment.original_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      setError('Failed to download file.');
    }
  };

  const handlePreview = async (attachment: Attachment) => {
    try {
      const res = await attachmentsApi.download(attachment.id);
      const url = URL.createObjectURL(new Blob([res.data], { type: attachment.content_type }));
      // Revoke any prior preview before assigning a new one.
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(url);
      setPreviewName(attachment.original_filename);
    } catch {
      setError('Failed to preview file.');
    }
  };

  const handleDelete = async (attachmentId: string) => {
    setDeletingId(attachmentId);
    setDeleteConfirmId(null);
    setError(null);
    try {
      await attachmentsApi.delete(attachmentId);
      await fetchAttachments();
    } catch {
      setError('Failed to delete attachment.');
    } finally {
      setDeletingId(null);
    }
  };

  const columnDefinitions = [
    {
      id: 'filename',
      header: 'File',
      cell: (item: Attachment) => (
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="inline-link" onClick={() => handleDownload(item)}>
            <Icon name="download" /> {item.original_filename}
          </Button>
          {isImageContentType(item.content_type) && (
            <Button
              variant="inline-link"
              ariaLabel={`Preview ${item.original_filename}`}
              onClick={() => handlePreview(item)}
            >
              Preview
            </Button>
          )}
        </SpaceBetween>
      ),
      sortingField: 'original_filename',
    },
    {
      id: 'size',
      header: 'Size',
      cell: (item: Attachment) => formatFileSize(item.file_size),
      width: 100,
    },
    {
      id: 'description',
      header: 'Description',
      cell: (item: Attachment) => item.description || '—',
    },
    {
      id: 'uploaded_by',
      header: 'Uploaded By',
      cell: (item: Attachment) => item.uploaded_by,
      width: 180,
    },
    {
      id: 'date',
      header: 'Date',
      cell: (item: Attachment) => new Date(item.created_at).toLocaleDateString(),
      width: 120,
    },
    ...(canEdit
      ? [
          {
            id: 'actions',
            header: '',
            cell: (item: Attachment) => (
              <Button
                variant="inline-icon"
                iconName="remove"
                ariaLabel="Delete attachment"
                loading={deletingId === item.id}
                onClick={() => setDeleteConfirmId(item.id)}
              />
            ),
            width: 50,
          },
        ]
      : []),
  ];

  if (!hasValidEntity) {
    return null;
  }

  return (
    <Container
      header={
        <Header variant="h2" counter={`(${items.length})`}>
          Attachments
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Table
          columnDefinitions={columnDefinitions}
          items={items}
          loading={loading}
          loadingText="Loading attachments..."
          empty={
            <Box textAlign="center" color="inherit" padding="m">
              No attachments yet.
            </Box>
          }
        />

        {canEdit && (
          <SpaceBetween size="xs">
            <FormField
              label="Upload File"
              description={
                limits
                  ? `Max ${limits.max_file_size_mb} MB. Allowed: ${limits.allowed_extensions.join(', ')}.`
                  : undefined
              }
            >
              <FileUpload
                accept={acceptAttribute}
                value={selectedFile ? [selectedFile] : []}
                onChange={({ detail }) => pickFile(detail.value[detail.value.length - 1] ?? null)}
                showFileLastModified
                showFileSize
                constraintText=""
                i18nStrings={{
                  uploadButtonText: () => 'Choose file',
                  dropzoneText: () => 'Drop a file to upload',
                  removeFileAriaLabel: (i) => `Remove file ${i + 1}`,
                  limitShowFewer: 'Show fewer files',
                  limitShowMore: 'Show more files',
                  errorIconAriaLabel: 'Error',
                }}
              />
            </FormField>
            <FormField label="Description (optional)">
              <Input
                value={description}
                onChange={({ detail }) => setDescription(detail.value)}
                placeholder="Brief description of this file..."
              />
            </FormField>
            {uploading && (
              <ProgressBar
                value={uploadProgress}
                description="Uploading..."
                additionalInfo={`${uploadProgress}%`}
              />
            )}
            <Button
              variant="primary"
              onClick={handleUpload}
              loading={uploading}
              disabled={!selectedFile}
            >
              Upload
            </Button>
          </SpaceBetween>
        )}
      </SpaceBetween>

      {/* Delete confirmation modal */}
      <Modal
        visible={!!deleteConfirmId}
        onDismiss={() => setDeleteConfirmId(null)}
        header="Delete Attachment"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                onClick={() => setDeleteConfirmId(null)}
                disabled={!!deletingId}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
                loading={!!deletingId}
              >
                Delete
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        Are you sure you want to delete this attachment? This action cannot be undone.
      </Modal>

      {/* Image preview modal */}
      <Modal
        visible={!!previewUrl}
        onDismiss={() => {
          if (previewUrl) URL.revokeObjectURL(previewUrl);
          setPreviewUrl(null);
        }}
        header={previewName}
        size="large"
        footer={
          <Box float="right">
            <Button
              onClick={() => {
                if (previewUrl) URL.revokeObjectURL(previewUrl);
                setPreviewUrl(null);
              }}
            >
              Close
            </Button>
          </Box>
        }
      >
        {previewUrl && (
          <Box textAlign="center">
            <img
              src={previewUrl}
              alt={previewName}
              style={{ maxWidth: '100%', maxHeight: '70vh' }}
            />
          </Box>
        )}
      </Modal>
    </Container>
  );
};

export default AttachmentsPanel;
