import React, { useEffect, useState } from 'react';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import Toggle from '@cloudscape-design/components/toggle';
import { sso as ssoApi } from '@/api';
import { useEntitlements } from '@/hooks/useEntitlements';
import type { SsoConfig } from '@/types';

const ROLE_OPTIONS = [
  { value: 'viewer', label: 'Viewer' },
  { value: 'editor', label: 'Editor' },
  { value: 'accountant', label: 'Accountant' },
  { value: 'admin', label: 'Administrator' },
];

const ReadOnlyValue: React.FC<{ label: string; value: string | null | undefined }> = ({
  label,
  value,
}) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>
      <span style={{ wordBreak: 'break-all', fontFamily: 'monospace' }}>{value || '—'}</span>
    </Box>
  </div>
);

const SsoSettingsPage: React.FC = () => {
  const { hasFeature, loading: entLoading } = useEntitlements();

  const [config, setConfig] = useState<SsoConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [issuer, setIssuer] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [domains, setDomains] = useState('');
  const [enforceSso, setEnforceSso] = useState(false);
  const [isEnabled, setIsEnabled] = useState(true);
  const [defaultRole, setDefaultRole] = useState('viewer');

  const applyConfig = (data: SsoConfig) => {
    setConfig(data);
    setIssuer(data.issuer || '');
    setClientId(data.client_id || '');
    setClientSecret('');
    setDomains((data.allowed_email_domains || []).join(', '));
    setEnforceSso(data.enforce_sso);
    setIsEnabled(data.configured ? data.is_enabled : true);
    setDefaultRole(data.default_role || 'viewer');
  };

  const load = async () => {
    setIsLoading(true);
    try {
      const { data } = await ssoApi.getConfig();
      applyConfig(data);
      setError(null);
    } catch {
      setError('Could not load the single sign-on configuration.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!entLoading && hasFeature('sso')) {
      load();
    } else if (!entLoading) {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entLoading]);

  const parsedDomains = domains
    .split(/[\s,]+/)
    .map((d) => d.trim().toLowerCase().replace(/^[@.]+/, ''))
    .filter(Boolean);

  const handleSave = async () => {
    if (!issuer.trim() || !clientId.trim()) {
      setError('Issuer URL and client ID are required.');
      return;
    }
    if (parsedDomains.length === 0) {
      setError('Add at least one allowed email domain.');
      return;
    }
    if (!config?.configured && !clientSecret.trim()) {
      setError('A client secret is required the first time you configure SSO.');
      return;
    }
    setIsSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const { data } = await ssoApi.saveConfig({
        issuer: issuer.trim(),
        client_id: clientId.trim(),
        client_secret: clientSecret.trim() || undefined,
        allowed_email_domains: parsedDomains,
        enforce_sso: enforceSso,
        is_enabled: isEnabled,
        default_role: defaultRole,
      });
      applyConfig(data);
      setSuccess('Single sign-on settings saved.');
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : 'Could not save the configuration. Check the issuer URL and try again.',
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleDisconnect = async () => {
    setIsSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await ssoApi.deleteConfig();
      await load();
      setSuccess('Single sign-on has been disconnected.');
    } catch {
      setError('Could not disconnect single sign-on.');
    } finally {
      setIsSaving(false);
    }
  };

  if (entLoading || isLoading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (!hasFeature('sso')) {
    return (
      <ContentLayout header={<Header variant="h1">Single Sign-On</Header>}>
        <Alert type="info" header="Available on the Enterprise plan">
          Single sign-on lets your team authenticate with your existing identity provider.
          Upgrade to Enterprise to enable it.
        </Alert>
      </ContentLayout>
    );
  }

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Connect an OpenID Connect identity provider so your team signs in with your existing directory."
        >
          Single Sign-On
        </Header>
      }
    >
      <SpaceBetween direction="vertical" size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        {success && (
          <Alert type="success" dismissible onDismiss={() => setSuccess(null)}>
            {success}
          </Alert>
        )}

        <Container header={<Header variant="h2">Give these to your identity provider</Header>}>
          <ColumnLayout columns={2} variant="text-grid">
            <ReadOnlyValue label="Redirect URI (callback)" value={config?.redirect_uri} />
            <ReadOnlyValue label="Sign-in link for your team" value={config?.login_url} />
          </ColumnLayout>
        </Container>

        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              {config?.configured && (
                <Button onClick={handleDisconnect} disabled={isSaving}>
                  Disconnect
                </Button>
              )}
              <Button variant="primary" loading={isSaving} onClick={handleSave}>
                Save
              </Button>
            </SpaceBetween>
          }
        >
          <Container header={<Header variant="h2">Identity provider</Header>}>
            <SpaceBetween direction="vertical" size="l">
              <FormField
                label="Issuer URL"
                description="The OpenID Connect issuer, for example https://login.microsoftonline.com/<tenant-id>/v2.0. Must use https."
              >
                <Input
                  value={issuer}
                  onChange={({ detail }) => setIssuer(detail.value)}
                  placeholder="https://idp.example.com"
                  disabled={isSaving}
                />
              </FormField>

              <FormField label="Client ID">
                <Input
                  value={clientId}
                  onChange={({ detail }) => setClientId(detail.value)}
                  placeholder="Application (client) ID"
                  disabled={isSaving}
                />
              </FormField>

              <FormField
                label="Client secret"
                description={
                  config?.configured
                    ? `Stored encrypted (${config.client_secret_hint}). Leave blank to keep the current secret.`
                    : 'Stored encrypted. It is never shown again after saving.'
                }
              >
                <Input
                  type="password"
                  value={clientSecret}
                  onChange={({ detail }) => setClientSecret(detail.value)}
                  placeholder={config?.configured ? 'Unchanged' : 'Paste the client secret'}
                  disabled={isSaving}
                />
              </FormField>

              <FormField
                label="Allowed email domains"
                description="Comma separated. Only verified addresses in these domains may sign in or be provisioned."
                constraintText={
                  parsedDomains.length > 0 ? `Will save as: ${parsedDomains.join(', ')}` : undefined
                }
              >
                <Input
                  value={domains}
                  onChange={({ detail }) => setDomains(detail.value)}
                  placeholder="yourcompany.com, yourcompany.net"
                  disabled={isSaving}
                />
              </FormField>

              <FormField
                label="Role for new accounts"
                description="Applied when someone signs in through SSO for the first time."
              >
                <Select
                  selectedOption={
                    ROLE_OPTIONS.find((o) => o.value === defaultRole) || ROLE_OPTIONS[0]
                  }
                  options={ROLE_OPTIONS}
                  onChange={({ detail }) => setDefaultRole(detail.selectedOption.value || 'viewer')}
                  disabled={isSaving}
                />
              </FormField>

              <Toggle
                checked={isEnabled}
                onChange={({ detail }) => setIsEnabled(detail.checked)}
                disabled={isSaving}
              >
                Enable single sign-on
              </Toggle>

              <Toggle
                checked={enforceSso}
                onChange={({ detail }) => setEnforceSso(detail.checked)}
                disabled={isSaving}
                description="Blocks password sign-in for everyone in this organization. Confirm SSO works before turning this on."
              >
                Require single sign-on
              </Toggle>
            </SpaceBetween>
          </Container>
        </Form>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default SsoSettingsPage;
