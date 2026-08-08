import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Textarea from '@cloudscape-design/components/textarea';
import Wizard from '@cloudscape-design/components/wizard';
import { wizardI18nStrings } from '@/components/common/wizardI18n';
import { emailTemplates } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type { EmailBranding } from '@/types';

/**
 * Guided setup for the wrapper applied to every email the product sends.
 *
 * Branding is the kind of task an admin does once and never returns to, so it
 * is presented as three short steps with a live preview beside them rather than
 * one long form of unexplained fields. Each step answers a plain question:
 * who is this from, what should it look like, and what has to appear at the
 * bottom.
 */

const DEFAULT_BRANDING: EmailBranding = {
  sender_name: null,
  reply_to: null,
  logo_url: null,
  header_color: '#232f3e',
  accent_color: '#0972d3',
  signature: null,
  footer_text: null,
  postal_address: null,
  is_active: true,
  is_configured: false,
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

interface Props {
  onSaved?: (branding: EmailBranding) => void;
}

const EmailBrandingWizard: React.FC<Props> = ({ onSaved }) => {
  const { addFlash } = useFlashbar();
  const [form, setForm] = useState<EmailBranding>(DEFAULT_BRANDING);
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewHtml, setPreviewHtml] = useState<string>('');

  const set = <K extends keyof EmailBranding>(key: K, value: EmailBranding[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    (async () => {
      try {
        const res = await emailTemplates.getBranding();
        setForm(res.data);
      } catch {
        // An org that has never configured branding simply starts from defaults.
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Preview against a real template so the admin sees the wrapper in context
  // rather than an abstract swatch.
  const refreshPreview = useCallback(async () => {
    try {
      const res = await emailTemplates.preview('lease_expiration', {});
      setPreviewHtml(res.data.html_body);
    } catch {
      setPreviewHtml('');
    }
  }, []);

  useEffect(() => {
    if (!loading) refreshPreview();
  }, [loading, refreshPreview]);

  const save = async () => {
    setSaving(true);
    try {
      const res = await emailTemplates.saveBranding({
        sender_name: form.sender_name || null,
        reply_to: form.reply_to || null,
        logo_url: form.logo_url || null,
        header_color: form.header_color,
        accent_color: form.accent_color,
        signature: form.signature || null,
        footer_text: form.footer_text || null,
        postal_address: form.postal_address || null,
        is_active: form.is_active,
      });
      setForm(res.data);
      addFlash({ type: 'success', content: 'Email branding saved.' });
      await refreshPreview();
      onSaved?.(res.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Could not save email branding.' });
    } finally {
      setSaving(false);
    }
  };

  const validateStep = (index: number): string | null => {
    if (index === 0) {
      if (form.reply_to && !EMAIL_RE.test(form.reply_to)) {
        return 'Enter a valid reply-to address, or leave it blank.';
      }
    }
    if (index === 1) {
      if (!HEX_RE.test(form.header_color)) return 'Header colour must be a hex value such as #232f3e.';
      if (!HEX_RE.test(form.accent_color)) return 'Accent colour must be a hex value such as #0972d3.';
    }
    return null;
  };

  const [stepError, setStepError] = useState<string | null>(null);

  const preview = useMemo(
    () => (
      <Container header={<Header variant="h3">Live preview</Header>}>
        {previewHtml ? (
          <iframe
            title="Email preview"
            srcDoc={previewHtml}
            style={{ width: '100%', height: 460, border: '1px solid #e9ebed', borderRadius: 4 }}
          />
        ) : (
          <Box color="text-body-secondary">Save to generate a preview.</Box>
        )}
        <Box variant="small" color="text-body-secondary" padding={{ top: 's' }}>
          Shown using the lease expiration reminder with sample data.
        </Box>
      </Container>
    ),
    [previewHtml],
  );

  const steps = [
    {
      title: 'Who it comes from',
      description: 'Recipients judge automated mail mostly by the sender.',
      content: (
        <SpaceBetween size="l">
          <FormField
            label="Sender name"
            description="Shown in the inbox instead of the system mailbox name."
            constraintText="For example: Acme Property Care"
          >
            <Input
              value={form.sender_name ?? ''}
              onChange={({ detail }) => set('sender_name', detail.value)}
              placeholder="Acme Property Care"
            />
          </FormField>
          <FormField
            label="Reply-to address"
            description="Where replies go. Without this, recipients reply into a no-reply mailbox."
          >
            <Input
              type="email"
              value={form.reply_to ?? ''}
              onChange={({ detail }) => set('reply_to', detail.value)}
              placeholder="property@acme.example"
            />
          </FormField>
        </SpaceBetween>
      ),
    },
    {
      title: 'How it looks',
      description: 'Your logo and colours on every message.',
      content: (
        <SpaceBetween size="l">
          <FormField
            label="Logo URL"
            description="A publicly reachable image. Leave blank to show your organization name instead."
          >
            <Input
              value={form.logo_url ?? ''}
              onChange={({ detail }) => set('logo_url', detail.value)}
              placeholder="https://cdn.acme.example/logo.png"
            />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Header colour" constraintText="Hex value, e.g. #232f3e">
              <Input
                value={form.header_color}
                onChange={({ detail }) => set('header_color', detail.value)}
              />
            </FormField>
            <FormField label="Accent colour" constraintText="Hex value, e.g. #0972d3">
              <Input
                value={form.accent_color}
                onChange={({ detail }) => set('accent_color', detail.value)}
              />
            </FormField>
          </ColumnLayout>
        </SpaceBetween>
      ),
    },
    {
      title: 'Signature and footer',
      description: 'What appears at the bottom of every message.',
      content: (
        <SpaceBetween size="l">
          <FormField label="Signature" description="Closing line, team name or contact number.">
            <Textarea
              rows={3}
              value={form.signature ?? ''}
              onChange={({ detail }) => set('signature', detail.value)}
              placeholder={'Acme Facilities Team\n(503) 555-0100'}
            />
          </FormField>
          <FormField
            label="Footer text"
            description="Explains why the recipient is getting the message."
          >
            <Textarea
              rows={2}
              value={form.footer_text ?? ''}
              onChange={({ detail }) => set('footer_text', detail.value)}
              placeholder="You receive this because you manage a property with Acme."
            />
          </FormField>
          <FormField
            label="Postal address"
            description="Bulk senders are generally required to include one."
          >
            <Textarea
              rows={2}
              value={form.postal_address ?? ''}
              onChange={({ detail }) => set('postal_address', detail.value)}
              placeholder="1 Harbor Way, Portland OR 97204"
            />
          </FormField>
        </SpaceBetween>
      ),
    },
  ];

  if (loading) {
    return <Box padding="l">Loading branding…</Box>;
  }

  return (
    <SpaceBetween size="l">
      {!form.is_configured && (
        <Alert type="info" header="Your emails currently use the default styling">
          Set a sender name and reply-to address so recipients recognise your organization
          and can reply to a real mailbox.
        </Alert>
      )}
      <ColumnLayout columns={2}>
        <div>
          {stepError && <Alert type="error">{stepError}</Alert>}
          <Wizard
            i18nStrings={wizardI18nStrings()}
            activeStepIndex={activeStepIndex}
            onNavigate={({ detail }) => {
              if (detail.requestedStepIndex > activeStepIndex) {
                const message = validateStep(activeStepIndex);
                if (message) {
                  setStepError(message);
                  return;
                }
              }
              setStepError(null);
              setActiveStepIndex(detail.requestedStepIndex);
            }}
            onCancel={() => setActiveStepIndex(0)}
            onSubmit={() => {
              const message = validateStep(activeStepIndex);
              if (message) {
                setStepError(message);
                return;
              }
              save();
            }}
            isLoadingNextStep={saving}
            submitButtonText="Save branding"
            steps={steps}
          />
        </div>
        {preview}
      </ColumnLayout>
      <Box float="right">
        <Button onClick={save} loading={saving} variant="primary">
          Save branding
        </Button>
      </Box>
    </SpaceBetween>
  );
};

export default EmailBrandingWizard;
