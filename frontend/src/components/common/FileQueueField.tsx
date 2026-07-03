import React from 'react';
import FileUploadField, { type QueuedFile } from './FileUploadField';

export type { QueuedFile };

interface FileQueueFieldProps {
  files: QueuedFile[];
  onChange: (files: QueuedFile[]) => void;
  disabled?: boolean;
}

/**
 * Deferred-upload file queue used by the full-page create forms. Thin wrapper
 * over the shared {@link FileUploadField} (Cloudscape `FileUpload`) so all
 * upload controls share one look and feel; the queued files are uploaded by the
 * caller after the entity is saved.
 */
const FileQueueField: React.FC<FileQueueFieldProps> = ({ files, onChange, disabled }) => (
  <FileUploadField files={files} onChange={onChange} disabled={disabled} />
);

export default FileQueueField;
