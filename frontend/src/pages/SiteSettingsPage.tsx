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
  app_name: 'Portfolio Desk',
  login_subtitle: 'Sign in to manage your offices, leases, and facilities',
  login_form_header: 'Sign In',
  login_form_description: 'Enter your credentials to access the application',
  support_email: '',
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
    if (!form.app_name.trim()) {
      setError('App Name is required.');
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await siteSettingsApi.update({
        app_name: form.app_name.trim(),
        login_subtitle: form.login_subtitle.trim(),
        login_form_header: form.login_form_header.trim(),
        login_form_description: form.login_form_description.trim(),
        support_email: form.support_email.trim(),
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
              { text: 'Site Settings', href: '/admin/site-settings' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Customize the branding and text displayed on the login page and navigation."
          >
            Site Settings
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
            Site settings saved successfully.
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
            <Container header={<Header variant="h2">Application Branding</Header>}>
              <SpaceBetween size="l">
                <FormField
                  label="App Name"
                  description="Displayed in the top navigation bar and side navigation header."
                  constraintText="Required"
                >
                  <Input
                    value={form.app_name}
                    onChange={({ detail }) => setForm((f) => ({ ...f, app_name: detail.value }))}
                    placeholder="e.g., Portfolio Desk"
                  />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Login Page</Header>}>
              <SpaceBetween size="l">
                <FormField
                  label="Page Subtitle"
                  description="Text shown beneath the app name on the login page."
                >
                  <Input
                    value={form.login_subtitle}
                    onChange={({ detail }) => setForm((f) => ({ ...f, login_subtitle: detail.value }))}
                    placeholder="e.g., Sign in to manage your offices, leases, and facilities"
                  />
                </FormField>

                <FormField
                  label="Form Header"
                  description="Heading inside the sign-in card."
                >
                  <Input
                    value={form.login_form_header}
                    onChange={({ detail }) => setForm((f) => ({ ...f, login_form_header: detail.value }))}
                    placeholder="e.g., Sign In"
                  />
                </FormField>

                <FormField
                  label="Form Description"
                  description="Subtext below the form header."
                >
                  <Textarea
                    value={form.login_form_description}
                    onChange={({ detail }) => setForm((f) => ({ ...f, login_form_description: detail.value }))}
                    placeholder="e.g., Enter your credentials to access the application"
                    rows={3}
                  />
                </FormField>
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Support</Header>}>
              <SpaceBetween size="l">
                <FormField
                  label="Support Email"
                  description="Address that receives support requests submitted from within the app. Admins can review and forward requests on the Support Requests page."
                >
                  <Input
                    type="email"
                    value={form.support_email}
                    onChange={({ detail }) => setForm((f) => ({ ...f, support_email: detail.value }))}
                    placeholder="e.g., support@yourcompany.com"
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
