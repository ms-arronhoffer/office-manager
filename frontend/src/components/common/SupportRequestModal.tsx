import React, { useCallback, useEffect, useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Alert from '@cloudscape-design/components/alert';
import Tabs from '@cloudscape-design/components/tabs';
import Badge from '@cloudscape-design/components/badge';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Spinner from '@cloudscape-design/components/spinner';
import { supportRequests } from '@/api';
import type { SupportRequest, SupportMessage } from '@/api';

interface SupportRequestModalProps {
  visible: boolean;
  onDismiss: () => void;
}

/**
 * Global "Contact support" dialog. Any authenticated user can submit a support
 * request and follow the two-way conversation: replies posted by support (from
 * the admin console or Administration page) appear in "Your requests", where
 * the user can respond.
 */
const SupportRequestModal: React.FC<SupportRequestModalProps> = ({ visible, onDismiss }) => {
  const [activeTab, setActiveTab] = useState('new');

  // ── New request form ──────────────────────────────────────────────────────
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // ── Your requests / threads ───────────────────────────────────────────────
  const [mine, setMine] = useState<SupportRequest[]>([]);
  const [loadingMine, setLoadingMine] = useState(false);
  const [threads, setThreads] = useState<Record<string, SupportMessage[]>>({});
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const resetForm = () => {
    setSubject('');
    setMessage('');
    setError(null);
    setSuccess(false);
  };

  const handleDismiss = () => {
    resetForm();
    setActiveTab('new');
    onDismiss();
  };

  const handleSubmit = async () => {
    if (!subject.trim() || !message.trim()) {
      setError('Both a subject and a message are required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await supportRequests.create({ subject: subject.trim(), message: message.trim() });
      setSuccess(true);
      setSubject('');
      setMessage('');
    } catch {
      setError('Failed to submit support request. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const loadMine = useCallback(async () => {
    setLoadingMine(true);
    try {
      const res = await supportRequests.listMine();
      setMine(res.data);
    } catch {
      /* silent — the list simply stays empty */
    } finally {
      setLoadingMine(false);
    }
  }, []);

  const loadThread = useCallback(async (id: string) => {
    try {
      const res = await supportRequests.messages(id);
      setThreads((prev) => ({ ...prev, [id]: res.data }));
    } catch {
      /* silent */
    }
  }, []);

  // Refresh "Your requests" whenever that tab is opened.
  useEffect(() => {
    if (visible && activeTab === 'mine') {
      loadMine();
    }
  }, [visible, activeTab, loadMine]);

  const handleSendReply = async (req: SupportRequest) => {
    const draft = (replyDrafts[req.id] || '').trim();
    if (!draft) return;
    setBusyId(req.id);
    try {
      await supportRequests.addMessage(req.id, draft);
      setReplyDrafts((prev) => ({ ...prev, [req.id]: '' }));
      await loadThread(req.id);
    } catch {
      /* silent */
    } finally {
      setBusyId(null);
    }
  };

  const renderThread = (req: SupportRequest) => {
    const msgs = threads[req.id];
    return (
      <SpaceBetween size="s">
        <Box variant="p" color="text-body-secondary">{req.message}</Box>
        {msgs === undefined ? (
          <Box><Spinner size="normal" /> Loading conversation…</Box>
        ) : msgs.length === 0 ? (
          <Box variant="small" color="text-status-inactive">No replies yet.</Box>
        ) : (
          msgs.map((m) => (
            <div
              key={m.id}
              style={{
                borderLeft: `3px solid ${m.is_from_admin ? '#0972d3' : '#5f6b7a'}`,
                paddingLeft: 10,
              }}
            >
              <Box variant="small" color="text-body-secondary">
                {m.is_from_admin ? 'Support' : (m.author_name || 'You')} ·{' '}
                {new Date(m.created_at).toLocaleString()}
              </Box>
              <Box variant="p">{m.body}</Box>
            </div>
          ))
        )}
        <FormField label="Reply">
          <Textarea
            value={replyDrafts[req.id] || ''}
            onChange={({ detail }) =>
              setReplyDrafts((prev) => ({ ...prev, [req.id]: detail.value }))
            }
            placeholder="Type your reply…"
            rows={3}
          />
        </FormField>
        <Box float="right">
          <Button
            variant="primary"
            loading={busyId === req.id}
            disabled={!(replyDrafts[req.id] || '').trim()}
            onClick={() => handleSendReply(req)}
          >
            Send reply
          </Button>
        </Box>
      </SpaceBetween>
    );
  };

  return (
    <Modal
      visible={visible}
      header="Support"
      onDismiss={handleDismiss}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={handleDismiss} disabled={submitting}>
              Close
            </Button>
            {activeTab === 'new' && !success && (
              <Button
                variant="primary"
                onClick={handleSubmit}
                loading={submitting}
                disabled={!subject.trim() || !message.trim()}
              >
                Submit
              </Button>
            )}
          </SpaceBetween>
        </Box>
      }
    >
      <Tabs
        activeTabId={activeTab}
        onChange={({ detail }) => setActiveTab(detail.activeTabId)}
        tabs={[
          {
            id: 'new',
            label: 'New request',
            content: (
              <Form>
                <SpaceBetween size="m">
                  {error && <Alert type="error">{error}</Alert>}
                  {success ? (
                    <Alert type="success">
                      Your support request has been submitted. You&apos;ll see any replies under
                      &quot;Your requests&quot;.
                    </Alert>
                  ) : (
                    <>
                      <Box variant="p" color="text-body-secondary">
                        Describe the issue or request and our team will follow up.
                      </Box>
                      <FormField label="Subject">
                        <Input
                          value={subject}
                          onChange={({ detail }) => setSubject(detail.value)}
                          placeholder="Brief summary of your request"
                        />
                      </FormField>
                      <FormField label="Message">
                        <Textarea
                          value={message}
                          onChange={({ detail }) => setMessage(detail.value)}
                          placeholder="Provide as much detail as possible"
                          rows={5}
                        />
                      </FormField>
                    </>
                  )}
                </SpaceBetween>
              </Form>
            ),
          },
          {
            id: 'mine',
            label: 'Your requests',
            content: (
              <SpaceBetween size="m">
                <Box float="right">
                  <Button iconName="refresh" onClick={loadMine} loading={loadingMine}>
                    Refresh
                  </Button>
                </Box>
                {loadingMine && mine.length === 0 ? (
                  <Box textAlign="center" padding="l"><Spinner /> Loading…</Box>
                ) : mine.length === 0 ? (
                  <Box textAlign="center" color="text-status-inactive" padding="l">
                    You haven&apos;t submitted any support requests yet.
                  </Box>
                ) : (
                  mine.map((req) => (
                    <ExpandableSection
                      key={req.id}
                      variant="container"
                      headerText={req.subject}
                      headerActions={
                        <Badge color={req.status === 'open' ? 'blue' : 'green'}>
                          {req.status}
                        </Badge>
                      }
                      onChange={({ detail }) => {
                        if (detail.expanded && threads[req.id] === undefined) {
                          loadThread(req.id);
                        }
                      }}
                    >
                      {renderThread(req)}
                    </ExpandableSection>
                  ))
                )}
              </SpaceBetween>
            ),
          },
        ]}
      />
    </Modal>
  );
};

export default SupportRequestModal;
