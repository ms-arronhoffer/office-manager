import React, { useCallback, useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Table from '@cloudscape-design/components/table';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Badge from '@cloudscape-design/components/badge';
import Link from '@cloudscape-design/components/link';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import FormField from '@cloudscape-design/components/form-field';
import Textarea from '@cloudscape-design/components/textarea';
import { useNavigate } from 'react-router-dom';
import { supportRequests } from '@/api';
import type { SupportRequest, SupportMessage } from '@/api';

const SupportRequestsPage: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<SupportRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [supportEmail, setSupportEmail] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [threads, setThreads] = useState<Record<string, SupportMessage[]>>({});
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [replyingId, setReplyingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reqRes, configRes] = await Promise.all([
        supportRequests.list(),
        supportRequests.getConfig(),
      ]);
      setItems(reqRes.data);
      setSupportEmail(configRes.data.support_email || '');
      setError(null);
    } catch {
      setError('Failed to load support requests.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleEmail = async (req: SupportRequest) => {
    setBusyId(req.id);
    setNotice(null);
    try {
      const res = await supportRequests.email(req.id);
      setNotice({ type: res.data.sent ? 'success' : 'warning', text: res.data.detail });
    } catch {
      setNotice({ type: 'error', text: 'Failed to send the support request email.' });
    } finally {
      setBusyId(null);
    }
  };

  const handleToggleStatus = async (req: SupportRequest) => {
    const next = req.status === 'open' ? 'resolved' : 'open';
    setBusyId(req.id);
    try {
      const res = await supportRequests.updateStatus(req.id, next);
      setItems((prev) => prev.map((r) => (r.id === req.id ? res.data : r)));
    } catch {
      setNotice({ type: 'error', text: 'Failed to update the request status.' });
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (req: SupportRequest) => {
    setBusyId(req.id);
    try {
      await supportRequests.remove(req.id);
      setItems((prev) => prev.filter((r) => r.id !== req.id));
    } catch {
      setNotice({ type: 'error', text: 'Failed to delete the request.' });
    } finally {
      setBusyId(null);
    }
  };

  const loadThread = useCallback(async (id: string) => {
    try {
      const res = await supportRequests.messages(id);
      setThreads((prev) => ({ ...prev, [id]: res.data }));
    } catch {
      setNotice({ type: 'error', text: 'Failed to load the conversation.' });
    }
  }, []);

  const handleReply = async (req: SupportRequest) => {
    const draft = (replyDrafts[req.id] || '').trim();
    if (!draft) return;
    setReplyingId(req.id);
    try {
      await supportRequests.addMessage(req.id, draft);
      setReplyDrafts((prev) => ({ ...prev, [req.id]: '' }));
      await loadThread(req.id);
      setNotice({ type: 'success', text: 'Reply sent to the requester.' });
    } catch {
      setNotice({ type: 'error', text: 'Failed to send the reply.' });
    } finally {
      setReplyingId(null);
    }
  };

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Administration', href: '/administration' },
              { text: 'Support Requests', href: '/support-requests' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Review support requests submitted from within the app and forward them to the configured support address."
            actions={<Button iconName="refresh" onClick={load} loading={loading}>Refresh</Button>}
          >
            Support Requests
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        {error && <Alert type="error" dismissible onDismiss={() => setError(null)}>{error}</Alert>}
        {notice && (
          <Alert type={notice.type} dismissible onDismiss={() => setNotice(null)}>
            {notice.text}
          </Alert>
        )}

        <Container header={<Header variant="h2">Support email</Header>}>
          {supportEmail ? (
            <Box variant="p">
              Support requests are forwarded to{' '}
              <Link href={`mailto:${supportEmail}`} external>{supportEmail}</Link>.
            </Box>
          ) : (
            <Box variant="p" color="text-status-warning">
              No support email is configured. Set the <code>SUPPORT_EMAIL</code> environment
              variable in your deployment configuration to forward support requests by email.
            </Box>
          )}
        </Container>

        <Table
          loading={loading}
          loadingText="Loading support requests..."
          items={items}
          trackBy="id"
          variant="container"
          empty={
            <Box textAlign="center" color="inherit" padding={{ vertical: 'l' }}>
              <b>No support requests</b>
              <Box variant="p" color="inherit">Submitted support requests will appear here.</Box>
            </Box>
          }
          columnDefinitions={[
            {
              id: 'subject',
              header: 'Subject',
              cell: (r) => (
                <ExpandableSection
                  headerText={r.subject}
                  variant="footer"
                  onChange={({ detail }) => {
                    if (detail.expanded && threads[r.id] === undefined) {
                      loadThread(r.id);
                    }
                  }}
                >
                  <SpaceBetween size="s">
                    <Box variant="p" data-testid="support-message">{r.message}</Box>
                    {(threads[r.id] || []).map((m) => (
                      <div
                        key={m.id}
                        style={{
                          borderLeft: `3px solid ${m.is_from_admin ? '#0972d3' : '#5f6b7a'}`,
                          paddingLeft: 10,
                        }}
                      >
                        <Box variant="small" color="text-body-secondary">
                          {m.is_from_admin ? (m.author_name || 'Support') : (m.author_name || 'Requester')} ·{' '}
                          {new Date(m.created_at).toLocaleString()}
                        </Box>
                        <Box variant="p">{m.body}</Box>
                      </div>
                    ))}
                    <FormField label="Reply to requester">
                      <Textarea
                        value={replyDrafts[r.id] || ''}
                        onChange={({ detail }) =>
                          setReplyDrafts((prev) => ({ ...prev, [r.id]: detail.value }))
                        }
                        placeholder="Type a reply — the requester is notified in-app"
                        rows={3}
                      />
                    </FormField>
                    <Box>
                      <Button
                        variant="primary"
                        loading={replyingId === r.id}
                        disabled={!(replyDrafts[r.id] || '').trim()}
                        onClick={() => handleReply(r)}
                      >
                        Send reply
                      </Button>
                    </Box>
                  </SpaceBetween>
                </ExpandableSection>
              ),
            },
            {
              id: 'requester',
              header: 'From',
              cell: (r) => r.requester_name || r.requester_email || 'Unknown',
              width: 200,
            },
            {
              id: 'status',
              header: 'Status',
              cell: (r) => (
                <Badge color={r.status === 'open' ? 'blue' : 'green'}>{r.status}</Badge>
              ),
              width: 110,
            },
            {
              id: 'created',
              header: 'Submitted',
              cell: (r) => new Date(r.created_at).toLocaleString(),
              width: 200,
            },
            {
              id: 'actions',
              header: 'Actions',
              cell: (r) => (
                <SpaceBetween direction="horizontal" size="xs">
                  <Button
                    iconName="envelope"
                    loading={busyId === r.id}
                    onClick={() => handleEmail(r)}
                  >
                    Email
                  </Button>
                  <Button
                    loading={busyId === r.id}
                    onClick={() => handleToggleStatus(r)}
                  >
                    {r.status === 'open' ? 'Resolve' : 'Reopen'}
                  </Button>
                  <Button
                    iconName="remove"
                    variant="icon"
                    loading={busyId === r.id}
                    ariaLabel="Delete support request"
                    onClick={() => handleDelete(r)}
                  />
                </SpaceBetween>
              ),
              width: 280,
            },
          ]}
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default SupportRequestsPage;
