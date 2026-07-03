import React from 'react';
import FormField from '@cloudscape-design/components/form-field';
import FileUpload from '@cloudscape-design/components/file-upload';

export interface QueuedFile {
  file: File;
  id: string;
}

interface FileUploadFieldProps {
  files: QueuedFile[];
  onChange: (files: QueuedFile[]) => void;
  disabled?: boolean;
  /** Field label. Defaults to "Attachments". */
  label?: string;
  /** Helper text under the control. Defaults to the deferred-upload note. */
  constraintText?: string;
  /** Allow selecting more than one file. Defaults to true. */
  multiple?: boolean;
  /** Comma-separated list of accepted file extensions/MIME types. */
  accept?: string;
}

let counter = 0;
function nextId(): string {
  counter += 1;
  return `${Date.now()}-${counter}`;
}

/**
 * Shared file picker built on the Cloudscape `FileUpload` widget. Exposes the
 * same `QueuedFile[]` contract used across the app so it is a drop-in for the
 * former raw `<input type="file">` fields, giving every create/edit surface a
 * consistent, polished upload control (multi-file tokens, remove buttons,
 * drag-and-drop) instead of a bare browser file input.
 */
const FileUploadField: React.FC<FileUploadFieldProps> = ({
  files,
  onChange,
  disabled,
  label = 'Attachments',
  constraintText = 'Optional — files will be uploaded after saving',
  multiple = true,
  accept,
}) => {
  // Preserve stable ids across renders by matching existing File references.
  const handleChange = (value: File[]) => {
    const next = value.map((file) => {
      const existing = files.find((qf) => qf.file === file);
      return existing ?? { file, id: nextId() };
    });
    onChange(next);
  };

  return (
    <FormField label={label} constraintText={constraintText}>
      <FileUpload
        multiple={multiple}
        accept={accept}
        value={files.map((qf) => qf.file)}
        onChange={({ detail }) => handleChange(detail.value)}
        showFileLastModified
        showFileSize
        tokenLimit={3}
        constraintText=""
        i18nStrings={{
          uploadButtonText: (multi) => (multi ? 'Choose files' : 'Choose file'),
          dropzoneText: (multi) => (multi ? 'Drop files to upload' : 'Drop file to upload'),
          removeFileAriaLabel: (i) => `Remove file ${i + 1}`,
          limitShowFewer: 'Show fewer files',
          limitShowMore: 'Show more files',
          errorIconAriaLabel: 'Error',
        }}
      />
    </FormField>
  );
};

export default FileUploadField;
