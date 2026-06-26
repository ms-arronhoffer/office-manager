import React, { useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { clientPortalInternal } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import { copyToClipboard } from '@/utils/clipboard';
import type { ClientPortalEntityType } from '@/types';

interface Props {
  entityType: ClientPortalEntityType;
  entityId: string;
}

/**
 * Admin-only panel that mints a single-use signup link for a landlord or
 * management company so they can self-serve their secondary contacts and
 * documents through the client portal.
 */
const ClientPortalInvitePanel: React.FC<Props> = ({ entityType, entityId }) => {
  const { addFlash } = useFlashbar();
  const [generating, setGenerating] = useState(false);
  const [signupLink, setSignupLink] = useState<string | null>(null);

  const label = entityType === 'management_company' ? 'management company' : 'landlord';

  const generate = async () => {
    setGenerating(true);
    try {
      const res = await clientPortalInternal.generateInvite(entityType, entityId);
      const fullUrl = `${window.location.origin}${res.data.signup_url}`;
      setSignupLink(fullUrl);
      addFlash({
        type: 'success',
        content: 'One-time signup link generated. Share it with the ' + label + ' to activate their portal.',
      });
    } catch {
      addFlash({ type: 'error', content: 'Failed to generate portal invite.' });
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Container
      header={
        <Header
          variant="h2"
          actions={
            <Button variant="normal" loading={generating} onClick={generate}>
              {signupLink ? 'Regenerate invite' : 'Generate portal invite'}
            </Button>
          }
        >
          Client Portal Access
        </Header>
      }
    >
      <SpaceBetween size="s">
        <Box color="text-body-secondary">
          Generate a single-use signup link. After the {label} activates it, they get a private link to manage their
          secondary contacts and upload documents — with read-only access to the rest of their profile.
        </Box>
        {signupLink && (
          <SpaceBetween direction="horizontal" size="xs">
            <Input value={signupLink} readOnly onChange={() => {}} />
            <Button
              iconName="copy"
              variant="normal"
              onClick={async () => {
                const ok = await copyToClipboard(signupLink);
                addFlash({
                  type: ok ? 'success' : 'error',
                  content: ok
                    ? 'Signup link copied to clipboard.'
                    : 'Could not copy automatically. Select the link and copy it manually.',
                });
              }}
            >
              Copy
            </Button>
          </SpaceBetween>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default ClientPortalInvitePanel;
