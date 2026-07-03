import React from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Form from '@cloudscape-design/components/form';
import Alert from '@cloudscape-design/components/alert';

export interface EntityFormModalProps {
  /** Whether the modal is shown. */
  visible: boolean;
  /** Modal header/title text. */
  title: string;
  /** Invoked when the primary (submit) button is pressed. */
  onSubmit: () => void;
  /** Invoked when the modal is dismissed or Cancel is pressed. */
  onCancel: () => void;
  /** Shows a loading spinner on the submit button and disables Cancel. */
  submitting?: boolean;
  /** Disables the submit button (e.g. when required fields are empty). */
  submitDisabled?: boolean;
  /** Inline error surfaced above the form body. */
  error?: string | null;
  /** Label for the primary button. Defaults to "Save". */
  submitLabel?: string;
  /** Label for the dismiss button. Defaults to "Cancel". */
  cancelLabel?: string;
  /** Cloudscape modal size. Defaults to "medium". */
  size?: 'small' | 'medium' | 'large' | 'max';
  /** Optional extra footer actions rendered before Cancel (e.g. Delete). */
  secondaryActions?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Canonical modal chrome for create/edit ("entity form") flows across the app.
 *
 * Renders a Cloudscape Modal whose body is wrapped in a Form with a consistent
 * inline error Alert and a standardized Cancel / primary footer, so every page
 * modal has the same look, feel, sizing, and error handling. Callers only need
 * to provide the fields and a submit handler.
 */
const EntityFormModal: React.FC<EntityFormModalProps> = ({
  visible,
  title,
  onSubmit,
  onCancel,
  submitting = false,
  submitDisabled = false,
  error,
  submitLabel = 'Save',
  cancelLabel = 'Cancel',
  size = 'medium',
  secondaryActions,
  children,
}) => (
  <Modal
    visible={visible}
    header={title}
    size={size}
    onDismiss={onCancel}
    footer={
      <Box float="right">
        <SpaceBetween direction="horizontal" size="xs">
          {secondaryActions}
          <Button variant="link" onClick={onCancel} disabled={submitting}>
            {cancelLabel}
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

export default EntityFormModal;
