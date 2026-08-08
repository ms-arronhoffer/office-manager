import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import Modal from '@cloudscape-design/components/modal';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Textarea from '@cloudscape-design/components/textarea';
import { emailTemplates } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type {
  EmailTemplateCatalogEntry,
  EmailTemplateDetail,
  EmailTemplatePreview,
} from '@/types';

/**
 * Editor for a single message: copy on the left, what the recipient sees on the
 * right.
 *
 * Two things make this safe for a non-technical admin. Merge fields are offered
 * as a clickable palette rather than documented syntax they have to remember,
 * and any placeholder the message cannot supply is called out immediately
 * instead of silently rendering as a gap in a sentence a landlord receives.
 */

interface Props {
  entry: EmailTemplateCatalogEntry;
  onClose: () => void;
  onChanged: () => void;
}

const EmailTemplateEditor: React.FC<Props> = ({ entry, onClose, onChanged }) => {
  const { addFlash } = useFlashbar();
  const [detail, setDetail] = useState<EmailTemplateDetail | null>(null);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [preview, setPreview] = useState<EmailTemplatePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [testTo, setTestTo] = useState('');
  const [testing, setTesting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await emailTemplates.get(entry.key);
      setDetail(res.data);
      setSubject(res.data.subject);
      setBody(res.data.body);
    } catch {
      addFlash({ type: 'error', content: 'Could not load this message.' });
    } finally {
      setLoading(false);
    }
  }, [entry.key, addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  // Re-render the preview as the author types, debounced so each keystroke does
  // not become a request.
  useEffect(() => {
    if (loading) return;
    const timer = window.setTimeout(async () => {
      try {
        const res = await emailTemplates.preview(entry.key, { subject, body });
        setPreview(res.data);
      } catch {
        setPreview(null);
      }
    }, 400);
    return () => window.clearTimeout(timer);
  }, [entry.key, subject, body, loading]);

  const dirty = useMemo(
    () => !!detail && (subject !== detail.subject || body !== detail.body),
    [detail, subject, body],
  );

  const save = async () => {
    setSaving(true);
    try {
      const res = await emailTemplates.save(entry.key, { subject, body, is_active: true });
      setDetail(res.data);
      addFlash({ type: 'success', content: `"${entry.label}" saved.` });
      onChanged();
    } catch (e: unknown) {
      const message = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: message || 'Could not save this message.' });
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    if (!window.confirm(`Discard your changes to "${entry.label}" and restore the default wording?`)) {
      return;
    }
    setSaving(true);
    try {
      const res = await emailTemplates.reset(entry.key);
      setDetail(res.data);
      setSubject(res.data.subject);
      setBody(res.data.body);
      addFlash({ type: 'success', content: 'Restored the default wording.' });
      onChanged();
    } catch {
      addFlash({ type: 'error', content: 'Could not restore the default wording.' });
    } finally {
      setSaving(false);
    }
  };

  const sendTest = async () => {
    setTesting(true);
    try {
      await emailTemplates.test(entry.key, { to: testTo, subject, body });
      addFlash({ type: 'success', content: `Test message sent to ${testTo}.` });
      setTestOpen(false);
    } catch (e: unknown) {
      const message = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: message || 'Could not send the test message.' });
    } finally {
      setTesting(false);
    }
  };

  if (loading || !detail) {
    return <Box padding="l">Loading message…</Box>;
  }

  return (
    <SpaceBetween size="l">
      <Header
        variant="h2"
        description={detail.description}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={onClose}>Back to all messages</Button>
            {detail.is_customized && (
              <Button onClick={reset} loading={saving}>
                Restore default
              </Button>
            )}
            <Button onClick={() => setTestOpen(true)} iconName="envelope">
              Send test
            </Button>
            <Button variant="primary" onClick={save} loading={saving} disabled={!dirty}>
              Save
            </Button>
          </SpaceBetween>
        }
      >
        {detail.label}
      </Header>

      {preview && preview.unknown_fields.length > 0 && (
        <Alert type="warning" header="Unrecognised merge fields">
          {preview.unknown_fields.map((f) => `{{${f}}}`).join(', ')} will be blank for
          recipients, because this message does not provide {preview.unknown_fields.length === 1 ? 'that field' : 'those fields'}.
          Use the palette below to insert a supported field.
        </Alert>
      )}

      <ColumnLayout columns={2}>
        <SpaceBetween size="l">
          <Container header={<Header variant="h3">Wording</Header>}>
            <SpaceBetween size="m">
              <FormField label="Subject">
                <Input value={subject} onChange={({ detail: d }) => setSubject(d.value)} />
              </FormField>
              <FormField
                label="Body"
                description="Basic HTML is supported. Your branding, signature and footer are added automatically."
              >
                <Textarea
                  rows={16}
                  value={body}
                  onChange={({ detail: d }) => setBody(d.value)}
                />
              </FormField>
            </SpaceBetween>
          </Container>

          <Container
            header={
              <Header variant="h3" description="Click a field to add it to the body.">
                Available merge fields
              </Header>
            }
          >
            <SpaceBetween direction="horizontal" size="xs">
              {detail.merge_fields.map((field) => (
                <Button
                  key={field.name}
                  onClick={() => setBody((prev) => `${prev}{{${field.name}}}`)}
                >
                  {field.label}
                </Button>
              ))}
            </SpaceBetween>
          </Container>
        </SpaceBetween>

        <Container
          header={
            <Header
              variant="h3"
              description="Rendered with sample data and your branding."
              actions={
                detail.is_customized ? (
                  <Badge color="blue">Customised</Badge>
                ) : (
                  <Badge color="grey">Default wording</Badge>
                )
              }
            >
              What the recipient sees
            </Header>
          }
        >
          <SpaceBetween size="s">
            <Box variant="awsui-key-label">Subject</Box>
            <Box fontWeight="bold">{preview?.subject ?? subject}</Box>
            <iframe
              title="Email preview"
              srcDoc={preview?.html_body ?? ''}
              style={{ width: '100%', height: 520, border: '1px solid #e9ebed', borderRadius: 4 }}
            />
          </SpaceBetween>
        </Container>
      </ColumnLayout>

      <Modal
        visible={testOpen}
        onDismiss={() => setTestOpen(false)}
        header="Send a test message"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setTestOpen(false)}>Cancel</Button>
              <Button
                variant="primary"
                loading={testing}
                disabled={!testTo.trim()}
                onClick={sendTest}
              >
                Send test
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box color="text-body-secondary">
            Sends this message, including any unsaved edits, using sample data.
          </Box>
          <FormField label="Send to">
            <Input
              type="email"
              value={testTo}
              onChange={({ detail: d }) => setTestTo(d.value)}
              placeholder="you@example.com"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default EmailTemplateEditor;
