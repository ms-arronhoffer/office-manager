import React, { useCallback, useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Tabs from '@cloudscape-design/components/tabs';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { waivers as waiversApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import type { WaiverTemplate, WaiverRequestItem, WaiverRecipientType } from '@/types';

const RECIPIENT_OPTIONS = [
  { label: 'Existing contact (email on file)', value: 'contact' },
  { label: 'Visitor (enter email)', value: 'visitor' },
];

const STATUS_INDICATOR: Record<string, 'success' | 'in-progress' | 'error' | 'pending' | 'stopped'> = {
  signed: 'success',
  sent: 'pending',
  viewed: 'in-progress',
  declined: 'error',
  expired: 'stopped',
};

const WaiversPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();

  const [activeTab, setActiveTab] = useState('templates');
  const [templates, setTemplates] = useState<WaiverTemplate[]>([]);
  const [requests, setRequests] = useState<WaiverRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  // Template editor modal
  const [templateModal, setTemplateModal] = useState(false);
  const [editing, setEditing] = useState<WaiverTemplate | null>(null);
  const [tName, setTName] = useState('');
  const [tDescription, setTDescription] = useState('');
  const [tBody, setTBody] = useState('');
  const [savingTemplate, setSavingTemplate] = useState(false);

  // Send modal
  const [sendModal, setSendModal] = useState(false);
  const [sendTemplateId, setSendTemplateId] = useState<string | null>(null);
  const [recipientType, setRecipientType] = useState<WaiverRecipientType>('visitor');
  const [recipientEmail, setRecipientEmail] = useState('');
  const [recipientName, setRecipientName] = useState('');
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tpls, reqs] = await Promise.all([
        waiversApi.listTemplates(),
        waiversApi.listRequests(),
      ]);
      setTemplates(tpls.data);
      setRequests(reqs.data);
      setForbidden(false);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 402) {
        setForbidden(true);
      } else {
        addFlash({ type: 'error', content: 'Failed to load waivers.' });
      }
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const openNewTemplate = () => {
    setEditing(null);
    setTName('');
    setTDescription('');
    setTBody('Hello {{recipient_name}},\n\nBy signing below you agree to the terms set out by {{organization_name}}.');
    setTemplateModal(true);
  };

  const openEditTemplate = (t: WaiverTemplate) => {
    setEditing(t);
    setTName(t.name);
    setTDescription(t.description ?? '');
    setTBody(t.body);
    setTemplateModal(true);
  };

  const saveTemplate = async () => {
    if (!tName.trim() || !tBody.trim()) {
      addFlash({ type: 'error', content: 'Name and body are required.' });
      return;
    }
    setSavingTemplate(true);
    try {
      if (editing) {
        await waiversApi.updateTemplate(editing.id, {
          name: tName,
          description: tDescription || null,
          body: tBody,
        });
      } else {
        await waiversApi.createTemplate({ name: tName, description: tDescription || null, body: tBody });
      }
      setTemplateModal(false);
      addFlash({ type: 'success', content: `Template ${editing ? 'updated' : 'created'}.` });
      load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save template.' });
    } finally {
      setSavingTemplate(false);
    }
  };

  const openSend = (templateId?: string) => {
    setSendTemplateId(templateId ?? (templates[0]?.id ?? null));
    setRecipientType('visitor');
    setRecipientEmail('');
    setRecipientName('');
    setSendModal(true);
  };

  const submitSend = async () => {
    if (!sendTemplateId || !recipientEmail.trim()) {
      addFlash({ type: 'error', content: 'Template and recipient email are required.' });
      return;
    }
    setSending(true);
    try {
      await waiversApi.send({
        template_id: sendTemplateId,
        recipient_type: recipientType,
        recipient_email: recipientEmail,
        recipient_name: recipientName || null,
      });
      setSendModal(false);
      setActiveTab('sent');
      addFlash({ type: 'success', content: 'Waiver sent for signature.' });
      load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to send waiver.' });
    } finally {
      setSending(false);
    }
  };

  const deleteTemplate = (t: WaiverTemplate) => {
    confirmDelete({
      itemName: t.name,
      onConfirm: async () => {
        try {
          await waiversApi.deleteTemplate(t.id);
          addFlash({ type: 'success', content: `Deleted "${t.name}".` });
          load();
        } catch {
          addFlash({ type: 'error', content: 'Failed to delete template.' });
        }
      },
    });
  };

  if (forbidden) {
    return (
      <ContentLayout header={<Header variant="h1">Digital Waivers</Header>}>
        <Alert type="info" header="Upgrade required">
          Digital Waivers &amp; e-signatures are available on the Pro and Enterprise plans. Upgrade
          your plan to send waivers and collect legally defensible electronic signatures.
        </Alert>
      </ContentLayout>
    );
  }

  return (
    <>
      {deleteModal}
      <ContentLayout
        header={
          <Header
            variant="h1"
            description="Send pre-built or custom waivers to any contact or visitor and collect ESIGN/UETA-compliant electronic signatures."
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={openNewTemplate}>New template</Button>
                <Button variant="primary" onClick={() => openSend()} disabled={templates.length === 0}>
                  Send waiver
                </Button>
              </SpaceBetween>
            }
          >
            Digital Waivers
          </Header>
        }
      >
        {loading ? (
          <Box textAlign="center" padding={{ top: 'xxxl' }}>
            <Spinner size="large" />
          </Box>
        ) : (
          <Tabs
            activeTabId={activeTab}
            onChange={(e) => setActiveTab(e.detail.activeTabId)}
            tabs={[
              {
                id: 'templates',
                label: 'Templates',
                content: (
                  <Container>
                    <Table<WaiverTemplate>
                      items={templates}
                      columnDefinitions={[
                        { id: 'name', header: 'Name', cell: (t) => t.name },
                        {
                          id: 'type',
                          header: 'Type',
                          cell: (t) => (
                            <Badge color={t.is_prebuilt ? 'blue' : 'grey'}>
                              {t.is_prebuilt ? 'Pre-built' : 'Custom'}
                            </Badge>
                          ),
                        },
                        { id: 'description', header: 'Description', cell: (t) => t.description || '—' },
                        {
                          id: 'actions',
                          header: '',
                          cell: (t) => (
                            <SpaceBetween direction="horizontal" size="xs">
                              <Button variant="inline-link" onClick={() => openSend(t.id)}>Send</Button>
                              <Button variant="inline-link" onClick={() => openEditTemplate(t)}>Edit</Button>
                              <Button variant="inline-link" onClick={() => deleteTemplate(t)}>Delete</Button>
                            </SpaceBetween>
                          ),
                        },
                      ]}
                      empty={<Box textAlign="center" color="inherit">No templates yet. Create one to get started.</Box>}
                    />
                  </Container>
                ),
              },
              {
                id: 'sent',
                label: 'Sent waivers',
                content: (
                  <Container>
                    <Table<WaiverRequestItem>
                      items={requests}
                      columnDefinitions={[
                        { id: 'title', header: 'Waiver', cell: (r) => r.title },
                        {
                          id: 'recipient',
                          header: 'Recipient',
                          cell: (r) => `${r.recipient_name ? r.recipient_name + ' · ' : ''}${r.recipient_email}`,
                        },
                        {
                          id: 'type',
                          header: 'Type',
                          cell: (r) => (r.recipient_type === 'visitor' ? 'Visitor' : 'Contact'),
                        },
                        {
                          id: 'status',
                          header: 'Status',
                          cell: (r) => (
                            <StatusIndicator type={STATUS_INDICATOR[r.status] || 'pending'}>
                              {r.status}
                            </StatusIndicator>
                          ),
                        },
                        {
                          id: 'sent',
                          header: 'Sent',
                          cell: (r) => (r.sent_at ? new Date(r.sent_at).toLocaleDateString() : '—'),
                        },
                        {
                          id: 'actions',
                          header: '',
                          cell: (r) =>
                            r.status === 'signed' ? (
                              <Button
                                variant="inline-link"
                                onClick={async () => {
                                  try {
                                    const res = await waiversApi.downloadPdf(r.id);
                                    const url = URL.createObjectURL(res.data as Blob);
                                    const a = document.createElement('a');
                                    a.href = url;
                                    a.download = `${r.title}.pdf`;
                                    a.click();
                                    URL.revokeObjectURL(url);
                                  } catch {
                                    addFlash({ type: 'error', content: 'Failed to download signed PDF.' });
                                  }
                                }}
                              >
                                Download PDF
                              </Button>
                            ) : (
                              '—'
                            ),
                        },
                      ]}
                      empty={<Box textAlign="center" color="inherit">No waivers sent yet.</Box>}
                    />
                  </Container>
                ),
              },
            ]}
          />
        )}
      </ContentLayout>

      <Modal
        visible={templateModal}
        onDismiss={() => setTemplateModal(false)}
        header={editing ? 'Edit template' : 'New template'}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setTemplateModal(false)} disabled={savingTemplate}>
                Cancel
              </Button>
              <Button variant="primary" onClick={saveTemplate} loading={savingTemplate}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Name">
            <Input value={tName} onChange={(e) => setTName(e.detail.value)} />
          </FormField>
          <FormField label="Description" description="Optional internal note.">
            <Input value={tDescription} onChange={(e) => setTDescription(e.detail.value)} />
          </FormField>
          <FormField
            label="Body"
            description="Use {{recipient_name}} and {{organization_name}} as merge fields."
          >
            <Textarea value={tBody} onChange={(e) => setTBody(e.detail.value)} rows={12} />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={sendModal}
        onDismiss={() => setSendModal(false)}
        header="Send waiver"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setSendModal(false)} disabled={sending}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submitSend} loading={sending}>
                Send
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Template">
            <Select
              selectedOption={
                sendTemplateId
                  ? {
                      value: sendTemplateId,
                      label: templates.find((t) => t.id === sendTemplateId)?.name || '',
                    }
                  : null
              }
              onChange={(e) => setSendTemplateId(e.detail.selectedOption.value ?? null)}
              options={templates.map((t) => ({ value: t.id, label: t.name }))}
              placeholder="Choose a template"
            />
          </FormField>
          <FormField label="Recipient type">
            <Select
              selectedOption={RECIPIENT_OPTIONS.find((o) => o.value === recipientType) || null}
              onChange={(e) => setRecipientType(e.detail.selectedOption.value as WaiverRecipientType)}
              options={RECIPIENT_OPTIONS}
            />
          </FormField>
          <FormField label="Recipient name" description="Optional.">
            <Input value={recipientName} onChange={(e) => setRecipientName(e.detail.value)} />
          </FormField>
          <FormField label="Recipient email">
            <Input
              type="email"
              value={recipientEmail}
              onChange={(e) => setRecipientEmail(e.detail.value)}
              placeholder="name@example.com"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
};

export default WaiversPage;
