import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Table from '@cloudscape-design/components/table';
import Select from '@cloudscape-design/components/select';
import FormField from '@cloudscape-design/components/form-field';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Spinner from '@cloudscape-design/components/spinner';
import Modal from '@cloudscape-design/components/modal';
import Input from '@cloudscape-design/components/input';
import Checkbox from '@cloudscape-design/components/checkbox';
import {
  quickbooks as qboApi,
  bankFeed as feedApi,
  bank as bankApi,
  gl as glApi,
  integrations as integrationsApi,
} from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import { openPlaidLink } from '@/lib/plaidLink';
import type {
  QuickBooksConnection,
  QuickBooksAccountMapping,
  BankFeedConnection,
  BankFeedProviderStatus,
  BankAccount,
  GLAccount,
  IntegrationReadiness,
  TenantIntegrationConfig,
  TenantIntegrationProvider,
} from '@/types';

const configurableProviders = new Set<TenantIntegrationProvider>([
  'resident_payments',
  'screening',
  'plaid',
]);

function statusIndicator(status: string | null) {
  if (status === 'connected') return <StatusIndicator type="success">Connected</StatusIndicator>;
  if (status === 'error') return <StatusIndicator type="error">Error</StatusIndicator>;
  if (status === 'reauth_required')
    return <StatusIndicator type="warning">Reconnect required</StatusIndicator>;
  return <StatusIndicator type="stopped">Not connected</StatusIndicator>;
}

const ConnectorsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [searchParams, setSearchParams] = useSearchParams();

  const [qbo, setQbo] = useState<QuickBooksConnection | null>(null);
  const [mappings, setMappings] = useState<QuickBooksAccountMapping[]>([]);
  const [glAccounts, setGlAccounts] = useState<GLAccount[]>([]);
  const [feedStatus, setFeedStatus] = useState<BankFeedProviderStatus | null>(null);
  const [connections, setConnections] = useState<BankFeedConnection[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [readiness, setReadiness] = useState<IntegrationReadiness[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const [linkModal, setLinkModal] = useState(false);
  const [linkAccountId, setLinkAccountId] = useState<string | null>(null);
  const [configProvider, setConfigProvider] = useState<TenantIntegrationProvider | null>(null);
  const [config, setConfig] = useState<TenantIntegrationConfig | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [configSecret, setConfigSecret] = useState('');
  const [configWebhookSecret, setConfigWebhookSecret] = useState('');
  const [configEnabled, setConfigEnabled] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [qboRes, feedRes, connRes, bankRes, glRes, readinessRes] = await Promise.allSettled([
      qboApi.getConnection(),
      feedApi.status(),
      feedApi.listConnections(),
      bankApi.listAccounts({ active_only: true }),
      glApi.listAccounts(),
      integrationsApi.readiness(),
    ]);
    if (qboRes.status === 'fulfilled') setQbo(qboRes.value.data);
    if (feedRes.status === 'fulfilled') setFeedStatus(feedRes.value.data);
    if (connRes.status === 'fulfilled') setConnections(connRes.value.data);
    if (bankRes.status === 'fulfilled') setBankAccounts(bankRes.value.data);
    if (glRes.status === 'fulfilled') setGlAccounts(glRes.value.data);
    if (readinessRes.status === 'fulfilled') {
      setReadiness(readinessRes.value.data.filter((item) => item.provider !== 'platform_stripe'));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const loadMappings = useCallback(async () => {
    try {
      const res = await qboApi.listAccountMappings();
      setMappings(res.data);
    } catch {
      /* mappings only exist once connected */
    }
  }, []);

  useEffect(() => {
    if (qbo?.connected) loadMappings();
  }, [qbo?.connected, loadMappings]);

  // Intuit redirects back here with ?code=&realmId=&state= after consent.
  useEffect(() => {
    const code = searchParams.get('code');
    const realmId = searchParams.get('realmId');
    if (!code || !realmId) return;
    const state = searchParams.get('state');
    (async () => {
      try {
        const res = await qboApi.completeCallback({ code, realm_id: realmId, state });
        setQbo(res.data);
        addFlash({ type: 'success', content: 'QuickBooks connected.' });
      } catch {
        addFlash({ type: 'error', content: 'Could not complete the QuickBooks connection.' });
      } finally {
        ['code', 'realmId', 'state'].forEach((k) => searchParams.delete(k));
        setSearchParams(searchParams, { replace: true });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const connectQbo = async () => {
    setBusy('qbo-connect');
    try {
      const res = await qboApi.getAuthorizeUrl();
      if (!res.data.configured || !res.data.authorize_url) {
        addFlash({
          type: 'error',
          content:
            res.data.detail ??
            'QuickBooks is not configured on this server. Set QBO_CLIENT_ID, QBO_CLIENT_SECRET and QBO_REDIRECT_URI.',
        });
        return;
      }
      window.location.href = res.data.authorize_url;
    } catch {
      addFlash({ type: 'error', content: 'Could not start the QuickBooks connection.' });
    } finally {
      setBusy(null);
    }
  };

  const runQboAction = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } catch {
      addFlash({ type: 'error', content: 'The QuickBooks request failed.' });
    } finally {
      setBusy(null);
    }
  };

  const verifyProvider = async (provider: string) => {
    setBusy(`verify-${provider}`);
    try {
      const response = await integrationsApi.verify(provider);
      addFlash({
        type: response.data.ok ? 'success' : 'warning',
        content: response.data.ok
          ? `${provider.replaceAll('_', ' ')} verification succeeded.`
          : response.data.error ?? 'Verification was not successful.',
      });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'The verification request failed.' });
    } finally {
      setBusy(null);
    }
  };

  const openConfig = async (provider: TenantIntegrationProvider) => {
    setBusy(`config-${provider}`);
    try {
      const response = await integrationsApi.getConfig(provider);
      const next = response.data;
      setConfig(next);
      setConfigEnabled(next.is_enabled);
      setConfigSecret('');
      setConfigWebhookSecret('');
      setConfigValues(
        Object.fromEntries(
          Object.entries(next)
            .filter(([, value]) => typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean')
            .map(([key, value]) => [key, String(value ?? '')]),
        ),
      );
      setConfigProvider(provider);
    } catch {
      addFlash({ type: 'error', content: 'Could not load tenant integration settings.' });
    } finally {
      setBusy(null);
    }
  };

  const setConfigValue = (key: string, value: string) =>
    setConfigValues((current) => ({ ...current, [key]: value }));

  const applicantWebhookUrl = `${window.location.origin}/api/v1/leasing-funnel/plaid/webhook`;
  const residentStripeWebhookUrl = configValues.webhook_key
    ? `${window.location.origin}/api/v1/resident-payments/stripe/webhook/${configValues.webhook_key}`
    : '';

  const configSettings = (): Record<string, unknown> => {
    if (configProvider === 'resident_payments') {
      return {
        provider: 'stripe',
        publishable_key: configValues.publishable_key ?? '',
        api_url: configValues.api_url ?? '',
      };
    }
    if (configProvider === 'screening') {
      return {
        provider_name: configValues.provider_name ?? '',
        api_url: configValues.api_url ?? '',
        health_url: configValues.health_url ?? '',
        poll_attempts: Number(configValues.poll_attempts || 5),
        poll_interval_seconds: Number(configValues.poll_interval_seconds || 2),
      };
    }
    return {
      client_id: configValues.client_id ?? '',
      environment: configValues.environment ?? 'sandbox',
      api_base_url: configValues.api_base_url ?? '',
      country_codes: (configValues.country_codes ?? 'US').split(',').map((code) => code.trim()),
      redirect_uri: configValues.redirect_uri ?? '',
      webhook_url: configValues.webhook_url || applicantWebhookUrl,
      applicant_redirect_uri: configValues.applicant_redirect_uri ?? '',
      applicant_verification_enabled: configValues.applicant_verification_enabled === 'true',
      resident_ach_redirect_uri: configValues.resident_ach_redirect_uri ?? '',
      resident_ach_webhook_url: configValues.resident_ach_webhook_url ?? '',
      resident_ach_enabled: configValues.resident_ach_enabled === 'true',
    };
  };

  const saveConfig = async () => {
    if (!configProvider) return;
    setBusy(`save-${configProvider}`);
    try {
      await integrationsApi.saveConfig(configProvider, {
        is_enabled: configEnabled,
        secret: configSecret || undefined,
        webhook_secret:
          configProvider === 'resident_payments' && configWebhookSecret
            ? configWebhookSecret
            : undefined,
        settings: configSettings(),
      });
      addFlash({ type: 'success', content: 'Tenant integration settings saved.' });
      setConfigProvider(null);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Could not save tenant integration settings.' });
    } finally {
      setBusy(null);
    }
  };

  const deleteConfig = async () => {
    if (!configProvider || !window.confirm('Disconnect this tenant integration configuration?')) return;
    setBusy(`delete-${configProvider}`);
    try {
      await integrationsApi.deleteConfig(configProvider);
      addFlash({ type: 'success', content: 'Tenant integration configuration removed.' });
      setConfigProvider(null);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Could not remove tenant integration settings.' });
    } finally {
      setBusy(null);
    }
  };

  const connectBank = async () => {
    if (!linkAccountId) return;
    setBusy('plaid');
    try {
      const tokenRes = await feedApi.createLinkToken();
      if (!tokenRes.data.configured || !tokenRes.data.link_token) {
        addFlash({
          type: 'error',
          content:
            tokenRes.data.detail ??
            'Plaid is not configured for this organization. Configure it in Integration readiness first.',
        });
        return;
      }
      const result = await openPlaidLink(tokenRes.data.link_token);
      if (!result) return; // user closed Link
      await feedApi.createConnection({
        public_token: result.publicToken,
        bank_account_id: linkAccountId,
        provider_account_id: result.metadata.accounts?.[0]?.id ?? null,
      });
      addFlash({ type: 'success', content: 'Bank account connected.' });
      setLinkModal(false);
      setLinkAccountId(null);
      await load();
    } catch (err) {
      addFlash({
        type: 'error',
        content: err instanceof Error ? err.message : 'Could not connect the bank account.',
      });
    } finally {
      setBusy(null);
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
        <Header
          variant="h1"
          description="Connect QuickBooks Online and a live bank feed so the ledger and reconciliation stay current without manual exports."
        >
          Accounting connections
        </Header>
      }
    >
      <SpaceBetween size="l">
        {readiness.length > 0 && (
          <Container
            header={
              <Header
                variant="h2"
                description="Configuration and provider evidence only. Live certification requires real credentials and the documented manual checks."
              >
                Integration readiness
              </Header>
            }
          >
            <Table<IntegrationReadiness>
              variant="embedded"
              items={readiness}
              columnDefinitions={[
                {
                  id: 'provider',
                  header: 'Provider',
                  cell: (item) => item.provider.replaceAll('_', ' '),
                },
                {
                  id: 'configured',
                  header: 'Configured',
                  cell: (item) => (
                    <StatusIndicator type={item.configured ? 'success' : 'stopped'}>
                      {item.configured ? 'Configured' : 'Missing configuration'}
                    </StatusIndicator>
                  ),
                },
                {
                  id: 'verified',
                  header: 'Verification',
                  cell: (item) => (
                    <StatusIndicator
                      type={item.verified === true ? 'success' : item.verified === false ? 'error' : 'pending'}
                    >
                      {item.verified === true
                        ? 'Verified'
                        : item.verified === false
                          ? 'Failed'
                          : 'Needs verification'}
                    </StatusIndicator>
                  ),
                },
                { id: 'mode', header: 'Mode', cell: (item) => item.mode },
                {
                  id: 'source',
                  header: 'Source',
                  cell: (item) => item.source === 'legacy_env' ? 'Legacy platform fallback' : item.source,
                },
                {
                  id: 'missing',
                  header: 'Missing',
                  cell: (item) => item.missing_config.join(', ') || '—',
                },
                {
                  id: 'action',
                  header: '',
                  cell: (item) => (
                    <SpaceBetween direction="horizontal" size="xs">
                      {configurableProviders.has(item.provider as TenantIntegrationProvider) && (
                        <Button
                          variant="inline-link"
                          loading={busy === `config-${item.provider}`}
                          onClick={() => openConfig(item.provider as TenantIntegrationProvider)}
                        >
                          Configure
                        </Button>
                      )}
                      {item.verification_supported && (
                        <Button
                          variant="inline-link"
                          loading={busy === `verify-${item.provider}`}
                          disabled={!item.configured}
                          onClick={() => verifyProvider(item.provider)}
                        >
                          Verify safely
                        </Button>
                      )}
                    </SpaceBetween>
                  ),
                },
              ]}
            />
          </Container>
        )}

        {/* ── QuickBooks ── */}
        <Container
          header={
            <Header
              variant="h2"
              description="Pushes posted journal entries to QuickBooks Online and maps its chart of accounts to yours."
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  {qbo?.connected && (
                    <>
                      <Button
                        loading={busy === 'qbo-pull'}
                        onClick={() =>
                          runQboAction('qbo-pull', async () => {
                            const res = await qboApi.pullAccounts();
                            addFlash({
                              type: 'success',
                              content: `Pulled ${res.data.pulled} accounts, auto-matched ${res.data.auto_matched}.`,
                            });
                            await loadMappings();
                          })
                        }
                      >
                        Pull chart of accounts
                      </Button>
                      <Button
                        variant="primary"
                        loading={busy === 'qbo-sync'}
                        onClick={() =>
                          runQboAction('qbo-sync', async () => {
                            const res = await qboApi.sync();
                            addFlash({
                              type: res.data.failed ? 'warning' : 'success',
                              content: `Pushed ${res.data.pushed}, skipped ${res.data.skipped}, failed ${res.data.failed}.`,
                            });
                            await load();
                          })
                        }
                      >
                        Sync now
                      </Button>
                      <Button
                        loading={busy === 'qbo-disconnect'}
                        onClick={() =>
                          runQboAction('qbo-disconnect', async () => {
                            if (!window.confirm('Disconnect QuickBooks?')) return;
                            await qboApi.disconnect();
                            addFlash({ type: 'success', content: 'QuickBooks disconnected.' });
                            await load();
                          })
                        }
                      >
                        Disconnect
                      </Button>
                    </>
                  )}
                  {!qbo?.connected && (
                    <Button variant="primary" loading={busy === 'qbo-connect'} onClick={connectQbo}>
                      Connect QuickBooks
                    </Button>
                  )}
                </SpaceBetween>
              }
            >
              QuickBooks Online
            </Header>
          }
        >
          <SpaceBetween size="m">
            {!qbo?.configured && (
              <Alert type="info" header="Not configured on this server">
                Set <code>QBO_CLIENT_ID</code>, <code>QBO_CLIENT_SECRET</code> and{' '}
                <code>QBO_REDIRECT_URI</code> in the backend environment, then restart the API.
              </Alert>
            )}
            {qbo?.last_error && <Alert type="error">{qbo.last_error}</Alert>}
            <ColumnLayout columns={4} variant="text-grid">
              <div>
                <Box variant="awsui-key-label">Status</Box>
                {statusIndicator(qbo?.status ?? null)}
              </div>
              <div>
                <Box variant="awsui-key-label">Company (realm)</Box>
                <Box>{qbo?.realm_id ?? '—'}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Environment</Box>
                <Box>{qbo?.environment ?? '—'}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Last sync</Box>
                <Box>{qbo?.last_sync_at ?? 'Never'}</Box>
              </div>
            </ColumnLayout>

            {qbo?.connected && (
              <Table<QuickBooksAccountMapping>
                variant="embedded"
                items={mappings}
                header={<Header variant="h3" counter={`(${mappings.length})`}>Account mapping</Header>}
                columnDefinitions={[
                  {
                    id: 'qbo',
                    header: 'QuickBooks account',
                    cell: (m) => m.qbo_account_name ?? m.qbo_account_id,
                  },
                  { id: 'type', header: 'Type', cell: (m) => m.qbo_account_type ?? '—' },
                  {
                    id: 'gl',
                    header: 'Maps to',
                    cell: (m) => (
                      <Select
                        selectedOption={
                          m.gl_account_id
                            ? { label: m.gl_account_name ?? m.gl_account_id, value: m.gl_account_id }
                            : null
                        }
                        placeholder="Not mapped"
                        options={glAccounts.map((a) => ({
                          label: `${a.code} ${a.name}`,
                          value: a.id,
                        }))}
                        onChange={({ detail }) =>
                          runQboAction(`map-${m.id}`, async () => {
                            const value = detail.selectedOption.value ?? null;
                            const res = await qboApi.updateAccountMapping(m.id, value);
                            setMappings((prev) =>
                              prev.map((row) => (row.id === m.id ? res.data : row)),
                            );
                          })
                        }
                      />
                    ),
                  },
                  {
                    id: 'override',
                    header: 'Manual',
                    cell: (m) => (m.manual_override ? 'Yes' : 'Auto'),
                  },
                ]}
                empty={
                  <Box textAlign="center" padding="m">
                    Pull the chart of accounts to build the mapping.
                  </Box>
                }
              />
            )}
          </SpaceBetween>
        </Container>

        {/* ── Bank feed ── */}
        <Container
          header={
            <Header
              variant="h2"
              description="Imports transactions straight from the bank so reconciliation no longer needs a CSV or OFX upload."
              actions={
                <Button
                  variant="primary"
                  disabled={bankAccounts.length === 0}
                  onClick={() => setLinkModal(true)}
                >
                  Connect a bank
                </Button>
              }
            >
              Live bank feed
            </Header>
          }
        >
          <SpaceBetween size="m">
            {!feedStatus?.configured && (
              <Alert type="info" header="Not configured for this organization">
                Configure Plaid in Integration readiness, then connect a bank account.
              </Alert>
            )}
            {bankAccounts.length === 0 && (
              <Alert type="warning">
                Create a bank account under Finance before connecting a feed, so imported
                transactions have somewhere to land.
              </Alert>
            )}
            <Table<BankFeedConnection>
              variant="embedded"
              items={connections}
              columnDefinitions={[
                {
                  id: 'institution',
                  header: 'Institution',
                  cell: (c) => c.institution_name ?? c.item_id,
                },
                {
                  id: 'account',
                  header: 'Ledger account',
                  cell: (c) => c.bank_account_name ?? c.bank_account_id,
                },
                { id: 'mask', header: 'Account', cell: (c) => (c.account_mask ? `••••${c.account_mask}` : '—') },
                { id: 'status', header: 'Status', cell: (c) => statusIndicator(c.status) },
                { id: 'last', header: 'Last sync', cell: (c) => c.last_sync_at ?? 'Never' },
                {
                  id: 'actions',
                  header: '',
                  cell: (c) => (
                    <SpaceBetween direction="horizontal" size="xs">
                      <Button
                        variant="inline-link"
                        loading={busy === `sync-${c.id}`}
                        onClick={() =>
                          runQboAction(`sync-${c.id}`, async () => {
                            const res = await feedApi.sync(c.id);
                            addFlash({
                              type: res.data.error ? 'warning' : 'success',
                              content: res.data.error
                                ? res.data.error
                                : `Imported ${res.data.imported}, updated ${res.data.updated}, removed ${res.data.deleted}.`,
                            });
                            await load();
                          })
                        }
                      >
                        Sync
                      </Button>
                      <Button
                        variant="inline-link"
                        onClick={() =>
                          runQboAction(`del-${c.id}`, async () => {
                            if (!window.confirm('Disconnect this bank feed?')) return;
                            await feedApi.deleteConnection(c.id);
                            await load();
                          })
                        }
                      >
                        Disconnect
                      </Button>
                    </SpaceBetween>
                  ),
                },
              ]}
              empty={
                <Box textAlign="center" padding="m">
                  No bank feeds connected yet.
                </Box>
              }
            />
          </SpaceBetween>
        </Container>
      </SpaceBetween>

      <Modal
        visible={configProvider !== null}
        onDismiss={() => setConfigProvider(null)}
        header={`Configure ${configProvider?.replaceAll('_', ' ') ?? 'integration'}`}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              {config?.source === 'tenant' && (
                <Button loading={busy?.startsWith('delete-')} onClick={deleteConfig}>Disconnect</Button>
              )}
              <Button onClick={() => setConfigProvider(null)}>Cancel</Button>
              <Button variant="primary" loading={busy?.startsWith('save-')} onClick={saveConfig}>
                Save to tenant
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {config && (
            <Alert type={config.source === 'legacy_env' ? 'warning' : 'info'}>
              Source: {config.source === 'legacy_env' ? 'Legacy platform fallback' : config.source}.
              {config.secret_hint ? ` Stored secret ${config.secret_hint}.` : ''}
            </Alert>
          )}
          <Checkbox checked={configEnabled} onChange={({ detail }) => setConfigEnabled(detail.checked)}>
            Enabled for this tenant
          </Checkbox>
          {configProvider === 'resident_payments' && (
            <>
              <FormField label="Stripe secret API key"><Input type="password" value={configSecret} placeholder={config?.secret_hint ?? ''} onChange={({ detail }) => setConfigSecret(detail.value)} /></FormField>
              <FormField label="Stripe publishable key"><Input value={configValues.publishable_key ?? ''} onChange={({ detail }) => setConfigValue('publishable_key', detail.value)} /></FormField>
              <FormField label="Payment API URL"><Input value={configValues.api_url ?? ''} onChange={({ detail }) => setConfigValue('api_url', detail.value)} /></FormField>
              <FormField
                label="Stripe webhook signing secret"
                description="Create a Stripe webhook for the endpoint below, then enter its whsec_ signing secret."
              >
                <Input type="password" value={configWebhookSecret} placeholder={config?.webhook_secret_hint ?? ''} onChange={({ detail }) => setConfigWebhookSecret(detail.value)} />
              </FormField>
              <FormField
                label="Resident payment webhook endpoint"
                description="Subscribe to charge.succeeded, charge.failed, charge.refunded, and charge.dispute.created. Save once to generate the endpoint."
              >
                <Input value={residentStripeWebhookUrl} readOnly placeholder="Save this tenant configuration to generate the endpoint." />
              </FormField>
            </>
          )}
          {configProvider === 'screening' && (
            <>
              <FormField label="Provider name"><Input value={configValues.provider_name ?? ''} onChange={({ detail }) => setConfigValue('provider_name', detail.value)} /></FormField>
              <FormField label="API key"><Input type="password" value={configSecret} placeholder={config?.secret_hint ?? ''} onChange={({ detail }) => setConfigSecret(detail.value)} /></FormField>
              <FormField label="API URL"><Input value={configValues.api_url ?? ''} onChange={({ detail }) => setConfigValue('api_url', detail.value)} /></FormField>
              <FormField label="Health URL"><Input value={configValues.health_url ?? ''} onChange={({ detail }) => setConfigValue('health_url', detail.value)} /></FormField>
              <ColumnLayout columns={2}>
                <FormField label="Poll attempts"><Input type="number" value={configValues.poll_attempts ?? '5'} onChange={({ detail }) => setConfigValue('poll_attempts', detail.value)} /></FormField>
                <FormField label="Poll interval seconds"><Input type="number" value={configValues.poll_interval_seconds ?? '2'} onChange={({ detail }) => setConfigValue('poll_interval_seconds', detail.value)} /></FormField>
              </ColumnLayout>
            </>
          )}
          {configProvider === 'plaid' && (
            <>
              <FormField label="Client ID"><Input value={configValues.client_id ?? ''} onChange={({ detail }) => setConfigValue('client_id', detail.value)} /></FormField>
              <FormField label="Secret"><Input type="password" value={configSecret} placeholder={config?.secret_hint ?? ''} onChange={({ detail }) => setConfigSecret(detail.value)} /></FormField>
              <FormField label="Environment"><Select selectedOption={{ label: configValues.environment ?? 'sandbox', value: configValues.environment ?? 'sandbox' }} options={['sandbox', 'development', 'production'].map((value) => ({ label: value, value }))} onChange={({ detail }) => setConfigValue('environment', detail.selectedOption.value ?? 'sandbox')} /></FormField>
              <FormField label="API base URL"><Input value={configValues.api_base_url ?? ''} onChange={({ detail }) => setConfigValue('api_base_url', detail.value)} /></FormField>
              <FormField label="Country codes"><Input value={configValues.country_codes ?? 'US'} onChange={({ detail }) => setConfigValue('country_codes', detail.value)} /></FormField>
              <FormField label="Redirect URI"><Input value={configValues.redirect_uri ?? ''} onChange={({ detail }) => setConfigValue('redirect_uri', detail.value)} /></FormField>
              <Checkbox checked={configValues.applicant_verification_enabled === 'true'} onChange={({ detail }) => setConfigValue('applicant_verification_enabled', String(detail.checked))}>Enable applicant financial verification</Checkbox>
              <Checkbox checked={configValues.resident_ach_enabled === 'true'} onChange={({ detail }) => setConfigValue('resident_ach_enabled', String(detail.checked))}>Enable resident ACH bank linking</Checkbox>
              <FormField label="Resident ACH OAuth redirect URI" description="Optional. Register this exact URL in Plaid before using OAuth institutions.">
                <Input value={configValues.resident_ach_redirect_uri ?? ''} placeholder={`${window.location.origin}/resident-portal`} onChange={({ detail }) => setConfigValue('resident_ach_redirect_uri', detail.value)} />
              </FormField>
              <FormField label="Resident ACH Plaid webhook URL" description="Optional Plaid Item webhook for resident bank-link status events.">
                <Input value={configValues.resident_ach_webhook_url ?? ''} onChange={({ detail }) => setConfigValue('resident_ach_webhook_url', detail.value)} />
              </FormField>
              <FormField
                label="Applicant verification webhook URL"
                description="Public HTTPS endpoint Plaid uses for signed verification status events."
              >
                <Input
                  value={configValues.webhook_url ?? ''}
                  placeholder={applicantWebhookUrl}
                  onChange={({ detail }) => setConfigValue('webhook_url', detail.value)}
                />
              </FormField>
              <FormField
                label="Applicant OAuth redirect URI"
                description="Optional. Register this exact URI in Plaid before saving it. Leave blank for non-OAuth Sandbox institutions."
              >
                <Input
                  value={configValues.applicant_redirect_uri ?? ''}
                  placeholder={`${window.location.origin}/financial-verify`}
                  onChange={({ detail }) => setConfigValue('applicant_redirect_uri', detail.value)}
                />
              </FormField>
            </>
          )}
          {config?.last_verify_error && <Alert type="error">{config.last_verify_error}</Alert>}
        </SpaceBetween>
      </Modal>

      <Modal
        visible={linkModal}
        onDismiss={() => setLinkModal(false)}
        header="Connect a bank"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setLinkModal(false)}>Cancel</Button>
              <Button
                variant="primary"
                disabled={!linkAccountId}
                loading={busy === 'plaid'}
                onClick={connectBank}
              >
                Continue to your bank
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <FormField
          label="Ledger bank account"
          description="Imported transactions are posted against this account for reconciliation."
        >
          <Select
            selectedOption={
              linkAccountId
                ? {
                    label:
                      bankAccounts.find((a) => a.id === linkAccountId)?.name ?? linkAccountId,
                    value: linkAccountId,
                  }
                : null
            }
            placeholder="Choose an account"
            options={bankAccounts.map((a) => ({ label: a.name, value: a.id }))}
            onChange={({ detail }) => setLinkAccountId(detail.selectedOption.value ?? null)}
          />
        </FormField>
      </Modal>
    </ContentLayout>
  );
};

export default ConnectorsPage;
