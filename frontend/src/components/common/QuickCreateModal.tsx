import React from 'react';
import EntityFormModal from './EntityFormModal';

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
 * Shared modal chrome for the "Add new" quick-create flow. Thin wrapper over
 * {@link EntityFormModal} (the canonical entity form modal) that keeps the
 * quick-create default submit label of "Create".
 */
const QuickCreateModal: React.FC<QuickCreateModalProps> = ({
  submitLabel = 'Create',
  ...rest
}) => <EntityFormModal submitLabel={submitLabel} {...rest} />;

export default QuickCreateModal;
