import React from 'react';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';

interface Props {
  /** Overrides the default copy for portals that address a different audience. */
  description?: React.ReactNode;
}

/**
 * Shared "bad or expired portal link" state for the external portals, so every
 * portal explains the failure the same way.
 */
const PortalAccessDenied: React.FC<Props> = ({ description }) => (
  <Box padding="xxl">
    <Alert type="error" header="Access denied">
      {description ??
        'This portal link is invalid or has expired. Please contact your property manager for a new link.'}
    </Alert>
  </Box>
);

export default PortalAccessDenied;
