import React, { useEffect, useState, useCallback } from 'react';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Box from '@cloudscape-design/components/box';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Badge from '@cloudscape-design/components/badge';
import Alert from '@cloudscape-design/components/alert';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { useFlashbar } from '@/context/FlashbarContext';
import { webhooks as webhooksApi } from '@/api';
import type { Webhook, WebhookDelivery } from '@/types';

const EVENT_OPTIONS = [
  { label: '* (all events)', value: '*' },
  { label: 'ticket.created', value: 'ticket.created' },
  { label: 'ticket.status_changed', value: 'ticket.status_changed' },
  { label: 'test.ping', value: 'test.ping' },
];

const KNOWN_EVENTS = ['ticket.created', 'ticket.status_changed', 'test.ping'];

const WebhooksPage: React.FC = () => {
  const { addFlashMessage } = useFlashbar();
  const [items, setItems] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);

  // Create/edit modal
  const [modalOpen, setModalOpen] = useState(false);
  const [editingWebhook, setEditingWebhook] = useState<Webhook | null>(null);
  const [url, setUrl] = useState('');
  const [eventsValue, setEventsValue] = useState('*');
  const [saving, setSaving] = useState(false);

  // Delivery history modal
  const [deliveryModalOpen, setDeliveryModalOpen] = useState(false);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([]);
  const [deliveryLoading, setDeliveryLoading] = useState(false);
  const [deliveryWebhookUrl, setDeliveryWebhookUrl] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await webhooksApi.list();
      setItems(res.data);
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to load webhooks.' });
    } finally {
      setLoading(false);
    }
  }, [addFlashMessage]);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditingWebhook(null);
    setUrl('');
    setEventsValue('*');
    setModalOpen(true);
  };

  const openEdit = (w: Webhook) => {
    setEditingWebhook(w);
    setUrl(w.url);
    setEventsValue(w.events);
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!url.trim()) return;
    setSaving(true);
    try {
      if (editingWebhook) {
        await webhooksApi.update(editingWebhook.id, { url: url.trim(), events: eventsValue });
        addFlashMessage({ type: 'success', content: 'Webhook updated.' });
      } else {
        await webhooksApi.create({ url: url.trim(), events: eventsValue });
        addFlashMessage({ type: 'success', content: 'Webhook created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to save webhook.' });
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (w: Webhook) => {
    try {
      await webhooksApi.update(w.id, { is_active: !w.is_active });
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to update webhook.' });
    }
  };

  const handleDelete = async (w: Webhook) => {
    if (!window.confirm(`Delete webhook for ${w.url}?`)) return;
    try {
      await webhooksApi.delete(w.id);
      addFlashMessage({ type: 'success', content: 'Webhook deleted.' });
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to delete webhook.' });
    }
  };

  const handleTest = async (w: Webhook) => {
    try {
      const res = await webhooksApi.test(w.id);
      const d = res.data;
      if (d.status === 'success') {
        addFlashMessage({ type: 'success', content: `Test ping delivered — HTTP ${d.response_code}.` });
      } else {
        addFlashMessage({ type: 'warning', content: `Test ping failed — ${d.response_body?.slice(0, 120) ?? 'no response'}.` });
      }
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Test delivery failed.' });
    }
  };

  const openDeliveries = async (w: Webhook) => {
    setDeliveries([]);
    setDeliveryWebhookUrl(w.url);
    setDeliveryModalOpen(true);
    setDeliveryLoading(true);
    try {
      const res = await webhooksApi.deliveries(w.id);
      setDeliveries(res.data);
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to load delivery history.' });
    } finally {
      setDeliveryLoading(false);
    }
  };

  const renderEvents = (events: string) => {
    if (!events || events.trim() === '*') {
      return <Badge color="blue">all events</Badge>;
    }
    return (
      <SpaceBetween direction="horizontal" size="xs">
        {events.split(',').map((e) => (
          <Badge key={e.trim()} color="grey">{e.trim()}</Badge>
        ))}
      </SpaceBetween>
    );
  };

  return (
    <SpaceBetween size="l">
      <Container
        header={
          <Header
            variant="h1"
            description="Send signed HTTP callbacks to your systems when events occur."
            actions={<Button variant="primary" onClick={openCreate}>Add webhook</Button>}
          >
            Webhooks
          </Header>
        }
      >
        <Alert type="info" header="Payload signing">
          Each delivery includes an <code>X-Signature: sha256=&lt;hex&gt;</code> header. Verify it
          with HMAC-SHA256 using the endpoint secret to ensure authenticity.
        </Alert>
      </Container>

      <Table
        loading={loading}
        items={items}
        columnDefinitions={[
          {
            id: 'url',
            header: 'Endpoint URL',
            cell: (w) => <code style={{ fontSize: 12 }}>{w.url}</code>,
            width: 320,
          },
          {
            id: 'events',
            header: 'Events',
            cell: (w) => renderEvents(w.events),
          },
          {
            id: 'status',
            header: 'Status',
            cell: (w) =>
              w.is_active
                ? <StatusIndicator type="success">Active</StatusIndicator>
                : <StatusIndicator type="stopped">Inactive</StatusIndicator>,
            width: 110,
          },
          {
            id: 'last_triggered',
            header: 'Last triggered',
            cell: (w) =>
              w.last_triggered_at
                ? new Date(w.last_triggered_at).toLocaleString()
                : <Box color="text-body-secondary">Never</Box>,
            width: 180,
          },
          {
            id: 'actions',
            header: '',
            cell: (w) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => handleTest(w)}>Test</Button>
                <Button variant="inline-link" onClick={() => openDeliveries(w)}>History</Button>
                <Button variant="inline-link" onClick={() => openEdit(w)}>Edit</Button>
                <Button variant="inline-link" onClick={() => handleToggle(w)}>
                  {w.is_active ? 'Disable' : 'Enable'}
                </Button>
                <Button variant="inline-link" onClick={() => handleDelete(w)}>Delete</Button>
              </SpaceBetween>
            ),
            width: 280,
          },
        ]}
        empty={
          <Box textAlign="center" color="inherit">
            <b>No webhooks</b>
            <Box padding={{ bottom: 's' }} color="text-body-secondary">
              Add an endpoint to start receiving event notifications.
            </Box>
          </Box>
        }
        header={<Header counter={`(${items.length})`}>Registered endpoints</Header>}
      />

      {/* Create / Edit Modal */}
      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editingWebhook ? 'Edit webhook' : 'Add webhook'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={saving} onClick={handleSave}
                disabled={!url.trim()}>
                {editingWebhook ? 'Save changes' : 'Create webhook'}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Endpoint URL" description="Must be publicly reachable (https:// recommended).">
            <Input
              value={url}
              onChange={({ detail }) => setUrl(detail.value)}
              placeholder="https://example.com/webhooks/office-manager"
              type="url"
            />
          </FormField>
          <FormField
            label="Events"
            description="Select which events to subscribe to, or choose * for all."
          >
            <Select
              selectedOption={
                EVENT_OPTIONS.find((o) => o.value === eventsValue) ??
                { label: eventsValue, value: eventsValue }
              }
              onChange={({ detail }) => setEventsValue(detail.selectedOption.value ?? '*')}
              options={[
                ...EVENT_OPTIONS,
                // Allow custom comma-separated value if already set
                ...(KNOWN_EVENTS.includes(eventsValue) || eventsValue === '*'
                  ? []
                  : [{ label: eventsValue, value: eventsValue }]),
              ]}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Delivery History Modal */}
      <Modal
        visible={deliveryModalOpen}
        onDismiss={() => setDeliveryModalOpen(false)}
        header={`Delivery history — ${deliveryWebhookUrl}`}
        size="large"
      >
        {deliveryLoading ? (
          <Box textAlign="center" padding="l">Loading…</Box>
        ) : deliveries.length === 0 ? (
          <Box color="text-body-secondary">No deliveries recorded yet.</Box>
        ) : (
          <SpaceBetween size="xs">
            {deliveries.map((d) => (
              <ExpandableSection
                key={d.id}
                headerText={
                  <SpaceBetween direction="horizontal" size="s">
                    <Badge color={d.status === 'success' ? 'green' : 'red'}>{d.status}</Badge>
                    <span>{d.event_type}</span>
                    {d.response_code && <Badge color="grey">HTTP {d.response_code}</Badge>}
                    <Box color="text-body-secondary" fontSize="body-s">
                      {new Date(d.created_at).toLocaleString()}
                    </Box>
                  </SpaceBetween>
                }
              >
                <SpaceBetween size="s">
                  {d.response_body && (
                    <Box>
                      <Box fontWeight="bold">Response</Box>
                      <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {d.response_body}
                      </pre>
                    </Box>
                  )}
                  {d.attempt_count > 1 && (
                    <Box color="text-body-secondary" fontSize="body-s">
                      Attempt {d.attempt_count} of 3
                      {d.next_retry_at && d.status === 'failed' && (
                        <> · Next retry {new Date(d.next_retry_at).toLocaleString()}</>
                      )}
                    </Box>
                  )}
                  {d.payload_snapshot && (
                    <Box>
                      <Box fontWeight="bold">Payload</Box>
                      <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {(() => {
                          try { return JSON.stringify(JSON.parse(d.payload_snapshot!), null, 2); }
                          catch { return d.payload_snapshot; }
                        })()}
                      </pre>
                    </Box>
                  )}
                </SpaceBetween>
              </ExpandableSection>
            ))}
          </SpaceBetween>
        )}
      </Modal>
    </SpaceBetween>
  );
};

export default WebhooksPage;
