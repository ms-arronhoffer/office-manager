import React from 'react';
import Modal from '@cloudscape-design/components/modal';
import Toggle from '@cloudscape-design/components/toggle';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import { usePreferences } from '@/context/PreferencesContext';

export interface DashboardWidget {
  id: string;
  label: string;
}

interface DashboardSettingsModalProps {
  visible: boolean;
  onDismiss: () => void;
  widgets: DashboardWidget[];
  widgetVisibility: Record<string, boolean>;
}

const DashboardSettingsModal: React.FC<DashboardSettingsModalProps> = ({
  visible,
  onDismiss,
  widgets,
  widgetVisibility,
}) => {
  const { setDashboardWidget } = usePreferences();

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header="Dashboard Settings"
      closeAriaLabel="Close"
      size="small"
    >
      <SpaceBetween size="m">
        <Box variant="p" color="text-body-secondary">
          Choose which sections to display on your dashboard.
        </Box>
        {widgets.map((widget) => (
          <Toggle
            key={widget.id}
            checked={widgetVisibility[widget.id] !== false}
            onChange={({ detail }) => setDashboardWidget(widget.id, detail.checked)}
          >
            {widget.label}
          </Toggle>
        ))}
      </SpaceBetween>
    </Modal>
  );
};

export default DashboardSettingsModal;
