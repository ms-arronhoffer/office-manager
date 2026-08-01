import React from 'react';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';

export interface EmptyStateProps {
  /** Short statement of what is missing, e.g. "No owners yet". */
  title: string;
  /** Optional one-line explanation of what this list is for. */
  description?: string;
  /** Label for the primary action. Omit to render a message-only state. */
  actionLabel?: string;
  onAction?: () => void;
}

/**
 * Table empty state that offers the first action instead of only reporting
 * that a list is empty.
 */
const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  actionLabel,
  onAction,
}) => (
  <Box textAlign="center" color="inherit" padding="l">
    <SpaceBetween size="s">
      <Box variant="strong">{title}</Box>
      {description && <Box color="text-body-secondary">{description}</Box>}
      {actionLabel && onAction && (
        <Box>
          <Button onClick={onAction}>{actionLabel}</Button>
        </Box>
      )}
    </SpaceBetween>
  </Box>
);

export default EmptyState;
