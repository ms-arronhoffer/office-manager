import React, { useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import { useNavigate } from 'react-router-dom';
import { siteSettings as siteSettingsApi } from '@/api';
import type { SiteSettings } from '@/api';
import { useSiteSettings } from '@/context/SiteSettingsContext';

const DEFAULTS: SiteSettings = {
  company_name: 'Portfolio Desk',
  company_address: '',
  company_phone: '',
  company_email: '',
  login_subtitle: 'Sign in to manage your offices, leases, and facilities',
  login_form_header: 'Sign In',
  login_form_description: 'Enter your credentials to access the application',
  sla_high_days: 1,
  sla_medium_days: 3,
  sla_low_days: 7,
};

const SiteSettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const { reload } = useSiteSettings();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [form, setForm] = useState<SiteSettings>(DEFAULTS);

  useEffect(() => {
    siteSettingsApi.get().then((res) => {
      setForm({ ...DEFAULTS, ...res.data });
    }).catch(() => {
      // Use defaults if fetch fails
    }).finally(() => {
      setLoading(false);
    });
  }, []);

  const handleSubmit = async () => {
    if (!form.company_name.trim()) {
      setError('Company Name is required.');
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await siteSettingsApi.update({
        company_name: form.company_name.trim(),
        company_address: form.company_address.trim(),
        company_phone: form.company_phone.trim(),
        company_email: form.company_email.trim(),
        login_subtitle: form.login_subtitle.trim(),
        login_form_header: form.login_form_header.trim(),
        login_form_description: form.login_form_description.trim(),
        sla_high_days: form.sla_high_days,
        sla_medium_days: form.sla_medium_days,
        sla_low_days: form.sla_low_days,
      });
      reload();
      setSuccess(true);
    } catch {
      setError('Failed to save site settings.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Settings', href: '/settings' },
              { text: 'Company Settings', href: '/admin/site-settings' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Customize the company branding and contact information displayed on reports and navigation."
          >
            Company Settings
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        {success && (
          <Alert type="success" dismissible onDismiss={() => setSuccess(false)}>
            Company settings saved successfully.
          </Alert>
        )}
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => navigate('/settings')}>Cancel</Button>
              <Button variant="primary" loading={saving} onClick={handleSubmit}>
                Save Changes
              </Button>
            </SpaceBetween>
          }
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Company Information</Header>}>
              <SpaceBetween size="l">
                <FormField
                  label="Company Name"
                  description="Used as the report header and shown in the side navigation."
                  constraintText="Required"
                >
                  <Input
                    value={form.company_name}
                    onChange={({ detail }) => setForm((f) => ({ ...f, company_name: detail.value }))}
                    placeholder="e.g., Acme Property Management"
                  />
                </FormField>

                <FormField
                  label="Company Address"
                  description="Shown as report header contact information."
                >
                  <Textarea
                    value={form.company_address}
                    onChange={({ detail }) => setForm((f) => ({ ...f, company_address: detail.value }))}
                    placeholder="e.g., 123 Main St, Suite 100, Anytown, ST 12345"
                    rows={2}
                  />
                </FormField>

                <FormField
                  label="Company Phone"
                  description="Shown as report header contact information."
                >
                  <Input
                    value={form.company_phone}
                    onChange={({ detail }) => setForm((f) => ({ ...f, company_phone: detail.value }))}
                    placeholder="e.g., (555) 123-4567"
                  />
                </FormField>

                <FormField
                  label="Company Email"
                  description="Shown as report header contact information."
                >
                  <Input
                    value={form.company_email}
                    onChange={({ detail }) => setForm((f) => ({ ...f, company_email: detail.value }))}
                    placeholder="e.g., contact@example.com"
                  />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">SLA Thresholds</Header>}>
              <SpaceBetween size="l">
                <Box variant="p" color="text-body-secondary">
                  Maximum days a ticket may remain open before it is considered an SLA breach.
                  These thresholds apply to the SLA dashboard analytics.
                </Box>
                <FormField label="High Priority (days)" description="Default: 1 day">
                  <Input
                    type="number"
                    value={String(form.sla_high_days)}
                    onChange={({ detail }) =>
                      setForm((f) => ({ ...f, sla_high_days: Math.max(1, parseInt(detail.value) || 1) }))
                    }
                    inputMode="numeric"
                  />
                </FormField>
                <FormField label="Medium Priority (days)" description="Default: 3 days">
                  <Input
                    type="number"
                    value={String(form.sla_medium_days)}
                    onChange={({ detail }) =>
                      setForm((f) => ({ ...f, sla_medium_days: Math.max(1, parseInt(detail.value) || 3) }))
                    }
                    inputMode="numeric"
                  />
                </FormField>
                <FormField label="Low Priority (days)" description="Default: 7 days">
                  <Input
                    type="number"
                    value={String(form.sla_low_days)}
                    onChange={({ detail }) =>
                      setForm((f) => ({ ...f, sla_low_days: Math.max(1, parseInt(detail.value) || 7) }))
                    }
                    inputMode="numeric"
                  />
                </FormField>
              </SpaceBetween>
            </Container>
          </SpaceBetween>
        </Form>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default SiteSettingsPage;
