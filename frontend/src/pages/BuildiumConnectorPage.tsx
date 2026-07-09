import React, { useCallback, useEffect, useRef, useState } from 'react';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Checkbox from '@cloudscape-design/components/checkbox';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import Modal from '@cloudscape-design/components/modal';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Table from '@cloudscape-design/components/table';
import Toggle from '@cloudscape-design/components/toggle';
import { useFlashbar } from '@/context/FlashbarContext';
import { buildium as buildiumApi, gl as glApi } from '@/api';
import type {
  BuildiumConnection,
  BuildiumEntityProgress,
  BuildiumEntityType,
  BuildiumGLAccountMapping,
  BuildiumMigrationRun,
  GLAccount,
} from '@/types';

const RUN_STATUS_TYPE: Record<string, 'success' | 'error' | 'in-progress' | 'pending' | 'stopped'> = {
  succeeded: 'success',
  failed: 'error',
  running: 'in-progress',
  pending: 'pending',
  partial: 'error',
  cancelled: 'stopped',
};

const ENTITY_PROGRESS_TOTAL = (p: BuildiumEntityProgress) => p.created + p.updated + p.skipped;

const BuildiumConnectorPage: React.FC = () => {
  const { addFlashMessage } = useFlashbar();

  // Connection state
  const [connection, setConnection] = useState<BuildiumConnection | null>(null);
  const [loadingConnection, setLoadingConnection] = useState(true);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [savingConnection, setSavingConnection] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);

  // GL mapping state
  const [glMappings, setGlMappings] = useState<BuildiumGLAccountMapping[]>([]);
  const [glAccounts, setGlAccounts] = useState<GLAccount[]>([]);
  const [loadingMapping, setLoadingMapping] = useState(false);

  // Execute state
  const [entityTypes, setEntityTypes] = useState<BuildiumEntityType[]>([]);
  const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set());
  const [dryRun, setDryRun] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [runs, setRuns] = useState<BuildiumMigrationRun[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadConnection = useCallback(async () => {
    setLoadingConnection(true);
    try {
      const res = await buildiumApi.getConnection();
      setConnection(res.data);
      setClientId(res.data.client_id ?? '');
      setBaseUrl(res.data.base_url ?? '');
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to load Buildium connection settings.' });
    } finally {
      setLoadingConnection(false);
    }
  }, [addFlashMessage]);

  const loadGlMapping = useCallback(async () => {
    setLoadingMapping(true);
    try {
      const [mappingRes, accountsRes] = await Promise.all([
        buildiumApi.listGlMapping(),
        glApi.listAccounts(),
      ]);
      setGlMappings(mappingRes.data);
      setGlAccounts(accountsRes.data);
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to load GL account mapping.' });
    } finally {
      setLoadingMapping(false);
    }
  }, [addFlashMessage]);

  const loadEntityTypes = useCallback(async () => {
    try {
      const res = await buildiumApi.listEntityTypes();
      setEntityTypes(res.data);
      setSelectedEntities(new Set(res.data.map((e) => e.key)));
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to load migration entity types.' });
    }
  }, [addFlashMessage]);

  const loadRuns = useCallback(async () => {
    try {
      const res = await buildiumApi.listRuns();
      setRuns(res.data);
      return res.data;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    loadConnection();
    loadGlMapping();
    loadEntityTypes();
    loadRuns();
  }, [loadConnection, loadGlMapping, loadEntityTypes, loadRuns]);

  // Poll while a run is active.
  useEffect(() => {
    const active = runs.some((r) => r.status === 'pending' || r.status === 'running');
    if (active && !pollRef.current) {
      pollRef.current = setInterval(() => { loadRuns(); }, 3000);
    }
    if (!active && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [runs, loadRuns]);

  const handleSaveConnection = async () => {
    if (!clientId.trim() || !clientSecret.trim()) return;
    setSavingConnection(true);
    try {
      await buildiumApi.saveConnection({
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
        base_url: baseUrl.trim() || undefined,
      });
      setClientSecret('');
      addFlashMessage({ type: 'success', content: 'Buildium connection saved.' });
      await loadConnection();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to save Buildium connection.' });
    } finally {
      setSavingConnection(false);
    }
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    try {
      const res = await buildiumApi.testConnection();
      if (res.data.ok) {
        addFlashMessage({ type: 'success', content: 'Connected to Buildium successfully.' });
      } else {
        addFlashMessage({ type: 'error', content: `Connection test failed: ${res.data.error ?? 'unknown error'}` });
      }
      await loadConnection();
    } catch (err: any) {
      addFlashMessage({
        type: 'error',
        content: err?.response?.data?.detail ?? 'Failed to test Buildium connection.',
      });
    } finally {
      setTestingConnection(false);
    }
  };

  const handleMappingChange = async (mapping: BuildiumGLAccountMapping, glAccountId: string) => {
    try {
      const res = await buildiumApi.updateGlMapping(mapping.id, glAccountId);
      setGlMappings((prev) => prev.map((m) => (m.id === mapping.id ? res.data : m)));
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to update GL account mapping.' });
    }
  };

  const toggleEntity = (key: string) => {
    setSelectedEntities((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const handleStartMigration = async () => {
    setStarting(true);
    try {
      await buildiumApi.startMigration({
        entities: selectedEntities.size === entityTypes.length ? null : Array.from(selectedEntities),
        dry_run: dryRun,
      });
      addFlashMessage({ type: 'success', content: `Migration ${dryRun ? 'dry run ' : ''}started.` });
      setConfirmOpen(false);
      await loadRuns();
    } catch (err: any) {
      addFlashMessage({
        type: 'error',
        content: err?.response?.data?.detail ?? 'Failed to start migration.',
      });
    } finally {
      setStarting(false);
    }
  };

  const handleCancelRun = async (run: BuildiumMigrationRun) => {
    try {
      await buildiumApi.cancelRun(run.id);
      addFlashMessage({ type: 'success', content: 'Migration run cancelled.' });
      await loadRuns();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to cancel migration run.' });
    }
  };

  const latestRun = runs[0];

  return (
    <SpaceBetween size="l">
      <Container
        header={
          <Header
            variant="h1"
            description="Migrate rental properties, units, owners, tenants, leases, and financials from Buildium into Portfolio Desk."
          >
            Buildium migration connector
          </Header>
        }
      >
        <Alert type="info" header="Admin only">
          This connector reads data from your Buildium account using an Open API client id/secret and
          upserts it into Portfolio Desk. Credentials are encrypted at rest and never displayed again
          after saving. Re-running a migration updates existing records rather than duplicating them.
        </Alert>
      </Container>

      <Container header={<Header variant="h2">Configuration</Header>}>
        {loadingConnection ? (
          <Box textAlign="center" padding="l">Loading…</Box>
        ) : (
          <SpaceBetween size="m">
            <ColumnLayout columns={2}>
              <FormField label="Client ID">
                <Input value={clientId} onChange={({ detail }) => setClientId(detail.value)} placeholder="Buildium client id" />
              </FormField>
              <FormField
                label="Client secret"
                description={
                  connection?.configured
                    ? `Currently set (${connection.client_secret_hint}). Leave blank-then-fill to rotate.`
                    : 'Not configured yet.'
                }
              >
                <Input
                  value={clientSecret}
                  onChange={({ detail }) => setClientSecret(detail.value)}
                  type="password"
                  placeholder={connection?.configured ? '••••••••' : 'Buildium client secret'}
                />
              </FormField>
            </ColumnLayout>
            <FormField label="Base URL" description="Defaults to https://api.buildium.com/v1 if left blank.">
              <Input value={baseUrl} onChange={({ detail }) => setBaseUrl(detail.value)} placeholder="https://api.buildium.com/v1" />
            </FormField>
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="primary"
                onClick={handleSaveConnection}
                loading={savingConnection}
                disabled={!clientId.trim() || !clientSecret.trim()}
              >
                Save connection
              </Button>
              <Button
                onClick={handleTestConnection}
                loading={testingConnection}
                disabled={!connection?.configured}
              >
                Test connection
              </Button>
            </SpaceBetween>
            {connection?.last_verified_at && (
              <Box color="text-body-secondary" fontSize="body-s">
                Last tested {new Date(connection.last_verified_at).toLocaleString()} —{' '}
                {connection.last_verify_ok ? (
                  <StatusIndicator type="success">OK</StatusIndicator>
                ) : (
                  <StatusIndicator type="error">{connection.last_verify_error ?? 'failed'}</StatusIndicator>
                )}
              </Box>
            )}
          </SpaceBetween>
        )}
      </Container>

      <Container
        header={
          <Header variant="h2" description="Map Buildium GL accounts (auto-created on first sync) to your local chart of accounts.">
            GL account mapping
          </Header>
        }
      >
        <Table
          loading={loadingMapping}
          items={glMappings}
          columnDefinitions={[
            { id: 'buildium', header: 'Buildium account', cell: (m) => m.buildium_account_name ?? m.buildium_gl_account_id },
            { id: 'type', header: 'Buildium type', cell: (m) => m.buildium_account_type ?? '—' },
            {
              id: 'mapped',
              header: 'Mapped to',
              cell: (m) => (
                <Select
                  selectedOption={
                    m.gl_account_id
                      ? { label: m.gl_account_name ?? m.gl_account_id, value: m.gl_account_id }
                      : null
                  }
                  placeholder="Select account"
                  options={glAccounts.map((a) => ({ label: `${a.code} — ${a.name}`, value: a.id }))}
                  onChange={({ detail }) => detail.selectedOption.value && handleMappingChange(m, detail.selectedOption.value)}
                />
              ),
            },
            {
              id: 'auto',
              header: 'Auto-created',
              cell: (m) => (m.auto_created ? <Badge color="blue">auto</Badge> : <Badge color="green">manual</Badge>),
              width: 130,
            },
          ]}
          empty={
            <Box textAlign="center" color="inherit">
              <b>No GL accounts mapped yet</b>
              <Box padding={{ bottom: 's' }} color="text-body-secondary">
                Mappings appear here after the first GL accounts migration pass runs.
              </Box>
            </Box>
          }
        />
      </Container>

      <Container
        header={
          <Header
            variant="h2"
            description="Select which entity types to migrate, then start the run. Dry run reports counts without writing any data."
            actions={
              <Button
                variant="primary"
                onClick={() => setConfirmOpen(true)}
                disabled={!connection?.configured || selectedEntities.size === 0 || (latestRun?.status === 'pending' || latestRun?.status === 'running')}
              >
                Start migration
              </Button>
            }
          >
            Execute
          </Header>
        }
      >
        <SpaceBetween size="m">
          <Toggle checked={dryRun} onChange={({ detail }) => setDryRun(detail.checked)}>
            Dry run (preview only, no data written)
          </Toggle>
          <ColumnLayout columns={3}>
            {entityTypes.map((e) => (
              <Checkbox key={e.key} checked={selectedEntities.has(e.key)} onChange={() => toggleEntity(e.key)}>
                {e.label}
              </Checkbox>
            ))}
          </ColumnLayout>
        </SpaceBetween>
      </Container>

      <Container header={<Header variant="h2" counter={`(${runs.length})`}>Migration runs</Header>}>
        <Table
          items={runs}
          columnDefinitions={[
            {
              id: 'status',
              header: 'Status',
              cell: (r) => (
                <StatusIndicator type={RUN_STATUS_TYPE[r.status] ?? 'pending'}>
                  {r.status}{r.dry_run ? ' (dry run)' : ''}
                </StatusIndicator>
              ),
              width: 180,
            },
            {
              id: 'started',
              header: 'Started',
              cell: (r) => (r.started_at ? new Date(r.started_at).toLocaleString() : '—'),
            },
            {
              id: 'finished',
              header: 'Finished',
              cell: (r) => (r.finished_at ? new Date(r.finished_at).toLocaleString() : '—'),
            },
            {
              id: 'progress',
              header: 'Progress',
              cell: (r) => (
                <SpaceBetween size="xs">
                  {Object.entries(r.progress || {}).map(([entity, p]) => (
                    <Box key={entity} fontSize="body-s">
                      {entity}: {ENTITY_PROGRESS_TOTAL(p)} processed
                      {p.errors.length > 0 && <> · <Box color="text-status-error" display="inline">{p.errors.length} error(s)</Box></>}
                    </Box>
                  ))}
                  {r.error_message && <Alert type="error">{r.error_message}</Alert>}
                </SpaceBetween>
              ),
            },
            {
              id: 'actions',
              header: '',
              cell: (r) =>
                (r.status === 'pending' || r.status === 'running') ? (
                  <Button variant="inline-link" onClick={() => handleCancelRun(r)}>Cancel</Button>
                ) : null,
              width: 100,
            },
          ]}
          empty={
            <Box textAlign="center" color="inherit">
              <b>No migration runs yet</b>
            </Box>
          }
        />
      </Container>

      <Modal
        visible={confirmOpen}
        onDismiss={() => setConfirmOpen(false)}
        header="Start Buildium migration"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setConfirmOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleStartMigration} loading={starting}>
                {dryRun ? 'Start dry run' : 'Start migration'}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="s">
          <Box>
            {dryRun
              ? 'This will preview the migration for the selected entity types without writing any data.'
              : 'This will write data into Portfolio Desk for the selected entity types. Re-running is safe — existing records are updated, not duplicated.'}
          </Box>
          <Box fontWeight="bold">Selected entities ({selectedEntities.size}):</Box>
          <Box>{Array.from(selectedEntities).join(', ') || 'none'}</Box>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default BuildiumConnectorPage;
