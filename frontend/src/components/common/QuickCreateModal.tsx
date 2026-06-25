import React from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Form from '@cloudscape-design/components/form';
import Alert from '@cloudscape-design/components/alert';

interface QuickCreateModalProps {
  visible: boolean;
  title: string;
  onSubmit: () => void;
  onCancel: () => void;
  submitting?: boolean;
  /** Disables the submit button (e.g. when required fields are empty). */
  submitDisabled?: boolean;
  error?: string | null;
  submitLabel?: string;
  children: React.ReactNode;
}

/**
 * Shared modal chrome for the "Add new" quick-create flow. Renders a Cloudscape
 * Modal with a Form body and Cancel/Create footer buttons so each entity's
 * quick-create form only has to provide its fields and a submit handler.
 */
const QuickCreateModal: React.FC<QuickCreateModalProps> = ({
  visible,
  title,
  onSubmit,
  onCancel,
  submitting = false,
  submitDisabled = false,
  error,
  submitLabel = 'Create',
  children,
}) => (
  <Modal
    visible={visible}
    header={title}
    onDismiss={onCancel}
    footer={
      <Box float="right">
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={onSubmit}
            loading={submitting}
            disabled={submitDisabled}
          >
            {submitLabel}
          </Button>
        </SpaceBetween>
      </Box>
    }
  >
    <Form>
      <SpaceBetween size="m">
        {error && <Alert type="error">{error}</Alert>}
        {children}
      </SpaceBetween>
    </Form>
  </Modal>
);

export default QuickCreateModal;
