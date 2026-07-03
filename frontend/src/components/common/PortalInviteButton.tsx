import React, { useState } from 'react';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import Input from '@cloudscape-design/components/input';
import FormField from '@cloudscape-design/components/form-field';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useFlashbar } from '@/context/FlashbarContext';
import { copyToClipboard } from '@/utils/clipboard';
import type { PortalInviteResponse } from '@/types';

interface Props {
  /** Human-readable entity label, e.g. "resident" or "owner". */
  entityLabel: string;
  /** Name of the entity being invited, shown in the confirmation copy. */
  entityName: string;
  /** Mints (or refreshes) the single-use portal invite for this entity. */
  onInvite: () => Promise<{ data: PortalInviteResponse }>;
}

/**
 * Admin-only inline action that mints a single-use portal signup link for a
 * resident or owner and surfaces it in a modal with a copy button.
 */
const PortalInviteButton: React.FC<Props> = ({ entityLabel, entityName, onInvite }) => {
  const { addFlash } = useFlashbar();
  const [generating, setGenerating] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [signupLink, setSignupLink] = useState('');
  const [expiresAt, setExpiresAt] = useState<string | null>(null);

  const invite = async () => {
    setGenerating(true);
    try {
      const res = await onInvite();
      setSignupLink(`${window.location.origin}${res.data.signup_url}`);
      setExpiresAt(res.data.expires_at);
      setModalOpen(true);
      addFlash({
        type: 'success',
        content: `One-time signup link generated. Share it with ${entityName} to activate their portal.`,
      });
    } catch {
      addFlash({ type: 'error', content: `Failed to generate ${entityLabel} portal invite.` });
    } finally {
      setGenerating(false);
    }
  };

  const copy = async () => {
    const ok = await copyToClipboard(signupLink);
    addFlash({
      type: ok ? 'success' : 'error',
      content: ok
        ? 'Link copied to clipboard.'
        : 'Could not copy automatically. Select the link and copy it manually.',
    });
  };

  return (
    <>
      <Button variant="inline-link" loading={generating} onClick={invite}>
        Invite to portal
      </Button>

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={`Portal invite for ${entityName}`}
        footer={
          <Box float="right">
            <Button variant="primary" onClick={() => setModalOpen(false)}>
              Done
            </Button>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box color="text-body-secondary">
            Share this single-use link with the {entityLabel}. After they activate it, they get a
            private link to their self-service portal.
            {expiresAt && ` The link expires ${new Date(expiresAt).toLocaleString()}.`}
          </Box>
          <FormField label="Signup link">
            <SpaceBetween direction="horizontal" size="xs">
              <Input value={signupLink} readOnly onChange={() => {}} />
              <Button iconName="copy" variant="normal" onClick={copy}>
                Copy
              </Button>
            </SpaceBetween>
          </FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
};

export default PortalInviteButton;
