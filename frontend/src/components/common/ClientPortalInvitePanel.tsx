import React, { useCallback, useEffect, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Input from '@cloudscape-design/components/input';
import Badge from '@cloudscape-design/components/badge';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { clientPortalInternal } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import { copyToClipboard } from '@/utils/clipboard';
import type {
  ClientPortalEntityType,
  ClientPortalStatus,
  ClientPortalStatusValue,
  ClientPortalChangeRequest,
} from '@/types';

interface Props {
  entityType: ClientPortalEntityType;
  entityId: string;
}

const STATUS_COLOR: Record<ClientPortalStatusValue, 'grey' | 'blue' | 'green' | 'red'> = {
  none: 'grey',
  invited: 'blue',
  active: 'green',
  revoked: 'red',
  expired: 'red',
};

const STATUS_LABEL: Record<ClientPortalStatusValue, string> = {
  none: 'Not invited',
  invited: 'Invited',
  active: 'Active',
  revoked: 'Revoked',
  expired: 'Expired',
};

const fmtDate = (v: string | null) => (v ? new Date(v).toLocaleString() : '—');

/**
 * Admin-only panel that manages a landlord / management-company client portal:
 * mint a single-use signup link, view access status, revoke or rotate the
 * credential, and review profile change requests submitted by the client.
 */
const ClientPortalInvitePanel: React.FC<Props> = ({ entityType, entityId }) => {
  const { addFlash } = useFlashbar();
  const [generating, setGenerating] = useState(false);
  const [signupLink, setSignupLink] = useState<string | null>(null);
  const [rotatedLink, setRotatedLink] = useState<string | null>(null);
  const [status, setStatus] = useState<ClientPortalStatus | null>(null);
  const [changeRequests, setChangeRequests] = useState<ClientPortalChangeRequest[]>([]);
  const [busy, setBusy] = useState(false);

  const label = entityType === 'management_company' ? 'management company' : 'landlord';

  const refresh = useCallback(async () => {
    try {
      const statusRes = await clientPortalInternal.status(entityType, entityId);
      setStatus(statusRes.data);
      if (statusRes.data.exists) {
        const crRes = await clientPortalInternal.listChangeRequests(entityType, entityId, 'pending');
        setChangeRequests(crRes.data);
      } else {
        setChangeRequests([]);
      }
    } catch {
      // Portal may be unavailable on the org plan; leave status null.
    }
  }, [entityType, entityId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const copy = async (link: string) => {
    const ok = await copyToClipboard(link);
    addFlash({
      type: ok ? 'success' : 'error',
      content: ok
        ? 'Link copied to clipboard.'
        : 'Could not copy automatically. Select the link and copy it manually.',
    });
  };

  const generate = async () => {
    setGenerating(true);
    try {
      const res = await clientPortalInternal.generateInvite(entityType, entityId);
      setSignupLink(`${window.location.origin}${res.data.signup_url}`);
      addFlash({
        type: 'success',
        content: `One-time signup link generated. Share it with the ${label} to activate their portal.`,
      });
      await refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to generate portal invite.' });
    } finally {
      setGenerating(false);
    }
  };

  const revoke = async () => {
    setBusy(true);
    try {
      const res = await clientPortalInternal.revoke(entityType, entityId);
      setStatus(res.data);
      setRotatedLink(null);
      addFlash({ type: 'success', content: 'Portal access revoked.' });
    } catch {
      addFlash({ type: 'error', content: 'Failed to revoke portal access.' });
    } finally {
      setBusy(false);
    }
  };

  const rotate = async () => {
    setBusy(true);
    try {
      const res = await clientPortalInternal.rotate(entityType, entityId);
      setRotatedLink(`${window.location.origin}${res.data.portal_url}`);
      addFlash({
        type: 'success',
        content: 'Portal access rotated. Share the new link; the previous one no longer works.',
      });
      await refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to rotate portal access.' });
    } finally {
      setBusy(false);
    }
  };

  const review = async (id: string, approve: boolean) => {
    setBusy(true);
    try {
      if (approve) await clientPortalInternal.approveChangeRequest(id);
      else await clientPortalInternal.rejectChangeRequest(id);
      addFlash({
        type: 'success',
        content: approve ? 'Change request approved and applied.' : 'Change request rejected.',
      });
      await refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to review change request.' });
    } finally {
      setBusy(false);
    }
  };

  const statusValue = status?.status ?? 'none';
  const isActive = statusValue === 'active';

  return (
    <Container
      header={
        <Header
          variant="h2"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              {isActive && (
                <Button variant="normal" disabled={busy} onClick={rotate}>
                  Rotate access
                </Button>
              )}
              {(isActive || statusValue === 'expired') && (
                <Button variant="normal" disabled={busy} onClick={revoke}>
                  Revoke access
                </Button>
              )}
              <Button variant="normal" loading={generating} onClick={generate}>
                {status?.exists ? 'Regenerate invite' : 'Generate portal invite'}
              </Button>
            </SpaceBetween>
          }
        >
          Client Portal Access
        </Header>
      }
    >
      <SpaceBetween size="m">
        <Box color="text-body-secondary">
          Generate a single-use signup link. After the {label} activates it, they get a private link
          to manage their secondary contacts, upload documents, and request profile corrections —
          with read-only access to the rest of their profile.
        </Box>

        {status && (
          <ColumnLayout columns={4} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Status</Box>
              <Badge color={STATUS_COLOR[statusValue]}>{STATUS_LABEL[statusValue]}</Badge>
            </div>
            <div>
              <Box variant="awsui-key-label">Activated</Box>
              <Box>{fmtDate(status.activated_at)}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Last active</Box>
              <Box>{fmtDate(status.last_active_at)}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Pending requests</Box>
              <Box>{status.pending_change_requests}</Box>
            </div>
          </ColumnLayout>
        )}

        {signupLink && (
          <SpaceBetween direction="horizontal" size="xs">
            <Input value={signupLink} readOnly onChange={() => {}} />
            <Button iconName="copy" variant="normal" onClick={() => copy(signupLink)}>
              Copy
            </Button>
          </SpaceBetween>
        )}

        {rotatedLink && (
          <SpaceBetween direction="horizontal" size="xs">
            <Input value={rotatedLink} readOnly onChange={() => {}} />
            <Button iconName="copy" variant="normal" onClick={() => copy(rotatedLink)}>
              Copy new link
            </Button>
          </SpaceBetween>
        )}

        {changeRequests.length > 0 && (
          <Table
            items={changeRequests}
            header={<Header variant="h3">Pending change requests</Header>}
            columnDefinitions={[
              {
                id: 'submitted',
                header: 'Submitted',
                cell: (r: ClientPortalChangeRequest) => new Date(r.created_at).toLocaleDateString(),
                width: 130,
              },
              {
                id: 'changes',
                header: 'Requested changes',
                cell: (r: ClientPortalChangeRequest) =>
                  Object.entries(r.proposed_changes)
                    .map(([k, v]) => `${k}: ${v ?? '(blank)'}`)
                    .join(', '),
              },
              {
                id: 'message',
                header: 'Note',
                cell: (r: ClientPortalChangeRequest) => r.message || '—',
              },
              {
                id: 'actions',
                header: '',
                cell: (r: ClientPortalChangeRequest) => (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button variant="inline-link" disabled={busy} onClick={() => review(r.id, true)}>
                      Approve
                    </Button>
                    <Button variant="inline-link" disabled={busy} onClick={() => review(r.id, false)}>
                      Reject
                    </Button>
                  </SpaceBetween>
                ),
                width: 170,
              },
            ]}
          />
        )}
      </SpaceBetween>
    </Container>
  );
};

export default ClientPortalInvitePanel;
