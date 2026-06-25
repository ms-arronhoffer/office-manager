import React, { useState } from 'react';
import FormField from '@cloudscape-design/components/form-field';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Icon from '@cloudscape-design/components/icon';

export interface QueuedFile {
  file: File;
  id: string;
}

interface FileQueueFieldProps {
  files: QueuedFile[];
  onChange: (files: QueuedFile[]) => void;
  disabled?: boolean;
}

const FileQueueField: React.FC<FileQueueFieldProps> = ({ files, onChange, disabled }) => {
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected) return;
    const newFiles: QueuedFile[] = Array.from(selected).map((f) => ({
      file: f,
      id: `${Date.now()}-${Math.random()}`,
    }));
    onChange([...files, ...newFiles]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeFile = (id: string) => {
    onChange(files.filter((f) => f.id !== id));
  };

  return (
    <FormField label="Attachments" constraintText="Optional — files will be uploaded after saving">
      <SpaceBetween size="xs">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          disabled={disabled}
          style={{ marginBottom: '4px' }}
        />
        {files.length > 0 && (
          <SpaceBetween size="xxs">
            {files.map((qf) => (
              <Box key={qf.id} display="inline-block">
                <SpaceBetween direction="horizontal" size="xxs">
                  <Icon name="file" />
                  <span>{qf.file.name}</span>
                  <Button
                    variant="inline-icon"
                    iconName="close"
                    ariaLabel={`Remove ${qf.file.name}`}
                    onClick={() => removeFile(qf.id)}
                    disabled={disabled}
                  />
                </SpaceBetween>
              </Box>
            ))}
          </SpaceBetween>
        )}
      </SpaceBetween>
    </FormField>
  );
};

export default FileQueueField;
