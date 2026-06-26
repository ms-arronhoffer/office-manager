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
import Autosuggest from '@cloudscape-design/components/autosuggest';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import TextFilter from '@cloudscape-design/components/text-filter';
import { waivers as waiversApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import type { WaiverTemplate, WaiverRequestItem, WaiverRecipientType, WaiverDuplicateCheck } from '@/types';

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
  const [requestQuery, setRequestQuery] = useState('');
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
  // Recipient typeahead + duplicate detection
  const [recipientSuggestions, setRecipientSuggestions] = useState<{ name: string | null; email: string; source: string }[]>([]);
  const [duplicate, setDuplicate] = useState<WaiverDuplicateCheck | null>(null);
  const [checkingDup, setCheckingDup] = useState(false);

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
    setRecipientSuggestions([]);
    setDuplicate(null);
    setSendModal(true);
  };

  // Typeahead: fetch candidate recipients from contacts + prior waivers.
  const loadRecipientSuggestions = useCallback(async (q: string) => {
    if (!q.trim()) {
      setRecipientSuggestions([]);
      return;
    }
    try {
      const res = await waiversApi.searchRecipients(q);
      setRecipientSuggestions(res.data);
    } catch {
      setRecipientSuggestions([]);
    }
  }, []);

  // Duplicate detection: warn if a waiver already exists for this email.
  const runDuplicateCheck = useCallback(
    async (email: string, templateId: string | null) => {
      const trimmed = email.trim();
      if (!trimmed) {
        setDuplicate(null);
        return;
      }
      setCheckingDup(true);
      try {
        const res = await waiversApi.checkDuplicate(trimmed, templateId);
        setDuplicate(res.data);
      } catch {
        setDuplicate(null);
      } finally {
        setCheckingDup(false);
      }
    },
    [],
  );

  const submitSend = async (force = false) => {
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
        force,
      });
      setSendModal(false);
      setActiveTab('sent');
      addFlash({ type: 'success', content: 'Waiver sent for signature.' });
      load();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        // A pending waiver already exists — surface the inline warning instead of
        // a generic error so the user can choose to send anyway.
        await runDuplicateCheck(recipientEmail, sendTemplateId);
        addFlash({
          type: 'warning',
          content: 'A waiver is already pending for this email. Review the warning and choose "Send anyway" to proceed.',
        });
      } else {
        addFlash({ type: 'error', content: 'Failed to send waiver.' });
      }
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

  const deleteRequest = (r: WaiverRequestItem) => {
    confirmDelete({
      itemName: r.recipient_name || r.recipient_email,
      onConfirm: async () => {
        try {
          await waiversApi.deleteRequest(r.id);
          addFlash({ type: 'success', content: 'Waiver deleted.' });
          load();
        } catch {
          addFlash({ type: 'error', content: 'Failed to delete waiver.' });
        }
      },
    });
  };

  const filteredRequests = React.useMemo(() => {
    const term = requestQuery.trim().toLowerCase();
    if (!term) return requests;
    return requests.filter((r) =>
      [r.title, r.recipient_name, r.recipient_email, r.status]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(term)),
    );
  }, [requests, requestQuery]);

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
                      items={filteredRequests}
                      filter={
                        <TextFilter
                          filteringText={requestQuery}
                          filteringPlaceholder="Search by recipient, email, title, or status"
                          filteringAriaLabel="Search waivers"
                          onChange={(e) => setRequestQuery(e.detail.filteringText)}
                          countText={
                            requestQuery.trim()
                              ? `${filteredRequests.length} match${filteredRequests.length === 1 ? '' : 'es'}`
                              : ''
                          }
                        />
                      }
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
                          cell: (r) => (
                            <SpaceBetween direction="horizontal" size="xs">
                              {r.status === 'signed' && (
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
                              )}
                              <Button variant="inline-link" onClick={() => deleteRequest(r)}>
                                Delete
                              </Button>
                            </SpaceBetween>
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
              {duplicate?.has_pending ? (
                <Button variant="primary" onClick={() => submitSend(true)} loading={sending}>
                  Send anyway
                </Button>
              ) : (
                <Button variant="primary" onClick={() => submitSend(false)} loading={sending}>
                  Send
                </Button>
              )}
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
              onChange={(e) => {
                const id = e.detail.selectedOption.value ?? null;
                setSendTemplateId(id);
                if (recipientEmail.trim()) runDuplicateCheck(recipientEmail, id);
              }}
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
          <FormField
            label="Recipient email"
            description="Start typing to search existing contacts and previous recipients."
          >
            <Autosuggest
              value={recipientEmail}
              onChange={(e) => {
                setRecipientEmail(e.detail.value);
                setDuplicate(null);
                loadRecipientSuggestions(e.detail.value);
              }}
              onSelect={(e) => {
                const picked = recipientSuggestions.find((s) => s.email === e.detail.value);
                if (picked?.name) setRecipientName(picked.name);
                runDuplicateCheck(e.detail.value, sendTemplateId);
              }}
              onBlur={() => runDuplicateCheck(recipientEmail, sendTemplateId)}
              options={recipientSuggestions.map((s) => ({
                value: s.email,
                label: s.email,
                description: s.name
                  ? `${s.name} · ${s.source === 'contact' ? 'Contact' : 'Previous recipient'}`
                  : s.source === 'contact'
                    ? 'Contact'
                    : 'Previous recipient',
              }))}
              enteredTextLabel={(v) => `Use "${v}"`}
              placeholder="name@example.com"
              statusType={checkingDup ? 'loading' : 'finished'}
              loadingText="Searching recipients…"
            />
          </FormField>
          {duplicate?.has_pending && (
            <Alert type="warning" header="A waiver already exists for this email">
              {duplicate.pending.length === 1
                ? `A "${duplicate.pending[0].title}" waiver is already ${duplicate.pending[0].status} for this recipient.`
                : `${duplicate.pending.length} waivers are already pending for this recipient.`}{' '}
              Choose “Send anyway” to send another, or cancel.
            </Alert>
          )}
        </SpaceBetween>
      </Modal>
    </>
  );
};

export default WaiversPage;
