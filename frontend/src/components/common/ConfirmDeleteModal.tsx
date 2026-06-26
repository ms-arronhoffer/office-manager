import React from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';

interface ConfirmDeleteModalProps {
  visible: boolean;
  itemName: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  /** Optional override of the default confirmation message. */
  description?: React.ReactNode;
}

const ConfirmDeleteModal: React.FC<ConfirmDeleteModalProps> = ({
  visible,
  itemName,
  onConfirm,
  onCancel,
  loading = false,
  description,
}) => (
  <Modal
    visible={visible}
    header="Confirm Delete"
    onDismiss={onCancel}
    footer={
      <Box float="right">
        <SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={onCancel} disabled={loading}>Cancel</Button>
          <Button variant="primary" onClick={onConfirm} loading={loading}>Delete</Button>
        </SpaceBetween>
      </Box>
    }
  >
    {description ?? (
      <>Are you sure you want to delete <strong>{itemName}</strong>? This action can be undone from the trash.</>
    )}
  </Modal>
);

export default ConfirmDeleteModal;
