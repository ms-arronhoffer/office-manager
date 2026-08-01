import React from 'react';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useNavigate } from 'react-router-dom';

export type UnavailableReason = 'role' | 'plan';

interface Props {
  /** What the user was trying to open, e.g. "Accounting". */
  featureName: string;
  /** Why it is unavailable: their role, or their organization's plan. */
  reason: UnavailableReason;
  /** Roles that can open this feature, shown for the 'role' reason. */
  allowedRoles?: string[];
  /** Plan that unlocks this feature, shown for the 'plan' reason. */
  requiredPlan?: string;
}

const ROLE_LABELS: Record<string, string> = {
  admin: 'Administrator',
  editor: 'Editor',
  accountant: 'Accountant',
  viewer: 'Viewer',
};

/**
 * Replaces the silent empty panel a user used to get when a feature was hidden
 * by their role or their organization's plan, so it is always clear what is
 * missing and who can restore access.
 */
const FeatureUnavailable: React.FC<Props> = ({
  featureName,
  reason,
  allowedRoles,
  requiredPlan,
}) => {
  const navigate = useNavigate();
  const roleList = (allowedRoles ?? [])
    .map((r) => ROLE_LABELS[r] ?? r)
    .join(' or ');

  return (
    <Container header={<Header variant="h2">{featureName} is not available to you</Header>}>
      <SpaceBetween size="m">
        {reason === 'role' ? (
          <Alert type="info" header="Your role does not include this feature">
            <SpaceBetween size="s">
              <Box>
                {roleList
                  ? `${featureName} is limited to the ${roleList} role. Ask an administrator in your organization to change your role if you need access.`
                  : `${featureName} is limited to specific roles. Ask an administrator in your organization if you need access.`}
              </Box>
              <Box color="text-body-secondary">
                Nothing is missing from your data — this view is simply restricted.
              </Box>
            </SpaceBetween>
          </Alert>
        ) : (
          <Alert type="info" header="Your plan does not include this feature">
            <SpaceBetween size="s">
              <Box>
                {requiredPlan
                  ? `${featureName} is included in the ${requiredPlan} plan and above.`
                  : `${featureName} is not enabled for your organization's plan.`}
              </Box>
              <Box>
                <Button onClick={() => navigate('/billing')}>View plans</Button>
              </Box>
            </SpaceBetween>
          </Alert>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default FeatureUnavailable;
