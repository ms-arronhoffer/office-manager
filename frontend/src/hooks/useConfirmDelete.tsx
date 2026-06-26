import React, { useCallback, useRef, useState } from 'react';
import ConfirmDeleteModal from '@/components/common/ConfirmDeleteModal';

interface ConfirmDeleteOptions {
  /** Name of the item shown in the confirmation prompt. */
  itemName: string;
  /** The delete action to run when the user confirms. */
  onConfirm: () => void | Promise<void>;
  /** Optional override for the default confirmation message. */
  description?: React.ReactNode;
}

interface UseConfirmDeleteResult {
  /** Opens the confirmation modal for the given item. */
  confirmDelete: (options: ConfirmDeleteOptions) => void;
  /** Render this element in the page to display the confirmation modal. */
  modal: React.ReactNode;
}

/**
 * Reusable delete-confirmation prompt. Prevents accidental deletions by
 * requiring an explicit confirmation before any destructive action runs.
 *
 * Usage:
 *   const { confirmDelete, modal } = useConfirmDelete();
 *   <Button onClick={() => confirmDelete({ itemName: name, onConfirm: handleDelete })}>Delete</Button>
 *   {modal}
 */
export function useConfirmDelete(): UseConfirmDeleteResult {
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [itemName, setItemName] = useState('');
  const [description, setDescription] = useState<React.ReactNode>(undefined);
  const actionRef = useRef<(() => void | Promise<void>) | null>(null);

  const confirmDelete = useCallback((options: ConfirmDeleteOptions) => {
    setItemName(options.itemName);
    setDescription(options.description);
    actionRef.current = options.onConfirm;
    setVisible(true);
  }, []);

  const handleCancel = useCallback(() => {
    if (loading) return;
    setVisible(false);
    actionRef.current = null;
  }, [loading]);

  const handleConfirm = useCallback(async () => {
    if (!actionRef.current) {
      setVisible(false);
      return;
    }
    try {
      setLoading(true);
      await actionRef.current();
      setVisible(false);
      actionRef.current = null;
    } finally {
      setLoading(false);
    }
  }, []);

  const modal = (
    <ConfirmDeleteModal
      visible={visible}
      itemName={itemName}
      description={description}
      loading={loading}
      onConfirm={handleConfirm}
      onCancel={handleCancel}
    />
  );

  return { confirmDelete, modal };
}

export default useConfirmDelete;
