import React from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';

interface KeyboardShortcutsModalProps {
  visible: boolean;
  onDismiss: () => void;
}

const SHORTCUTS = [
  { keys: 'Ctrl + K', description: 'Focus global search' },
  { keys: '?', description: 'Show keyboard shortcuts' },
  { keys: 'Escape', description: 'Close modals and dialogs' },
];

const KeyboardShortcutsModal: React.FC<KeyboardShortcutsModalProps> = ({ visible, onDismiss }) => (
  <Modal
    visible={visible}
    onDismiss={onDismiss}
    header="Keyboard Shortcuts"
    closeAriaLabel="Close"
    size="small"
  >
    <SpaceBetween size="s">
      <Table
        variant="embedded"
        columnDefinitions={[
          {
            id: 'keys',
            header: 'Shortcut',
            cell: (item) => (
              <Box fontWeight="bold">
                <code style={{ padding: '2px 6px', borderRadius: '4px', background: 'var(--color-background-input-default, #f2f3f3)' }}>
                  {item.keys}
                </code>
              </Box>
            ),
            width: 140,
          },
          {
            id: 'description',
            header: 'Action',
            cell: (item) => item.description,
          },
        ]}
        items={SHORTCUTS}
      />
    </SpaceBetween>
  </Modal>
);

export default KeyboardShortcutsModal;
