import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Button from '@cloudscape-design/components/button';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Link from '@cloudscape-design/components/link';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Table from '@cloudscape-design/components/table';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import { maintenance as maintApi } from '@/api';
import type { MaintenanceAsset, MaintenanceLog, MaintenanceTask } from '@/types';

const date = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleDateString() : '—';

const money = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const daysUntil = (v: string | null | undefined): number | null => {
  if (!v) return null;
  const diff = new Date(v).getTime() - Date.now();
  return Math.ceil(diff / 86_400_000);
};

const taskStatus = (t: MaintenanceTask): 'error' | 'warning' | 'success' => {
  const days = daysUntil(t.next_due_date);
  if (days == null) return 'success';
  if (days < 0) return 'error';
  if (days <= 30) return 'warning';
  return 'success';
};

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value || '—'}</Box>
  </div>
);

/**
 * Asset master record — the compliance and service picture for one piece of
 * equipment: what is scheduled, what is overdue, what it has cost, and what
 * certification is about to lapse. Previously this required cross-referencing
 * the maintenance category panel against the service log.
 */
const AssetDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [asset, setAsset] = useState<MaintenanceAsset | null>(null);
  const [tasks, setTasks] = useState<MaintenanceTask[]>([]);
  const [logs, setLogs] = useState<MaintenanceLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const assetRes = await maintApi.getAsset(id);
      setAsset(assetRes.data);
      const [taskRes, logRes] = await Promise.all([
        maintApi.listTasks({ asset_id: id }).catch(() => ({ data: [] as MaintenanceTask[] })),
        maintApi.listLogs({ asset_id: id }).catch(() => ({ data: [] as MaintenanceLog[] })),
      ]);
      setTasks(taskRes.data);
      setLogs(logRes.data);
    } catch {
      setError('Failed to load asset.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const overdueCount = useMemo(
    () => tasks.filter((t) => (daysUntil(t.next_due_date) ?? 1) < 0).length,
    [tasks],
  );

  const lifetimeCost = useMemo(
    () => logs.reduce((sum, l) => sum + Number(l.cost ?? 0), 0),
    [logs],
  );

  const certDays = daysUntil(asset?.certification_expiry);

  const generateWorkOrder = async (task: MaintenanceTask) => {
    try {
      const res = await maintApi.generateWorkOrder(task.id);
      addFlash({ type: 'success', content: res.data.detail || 'Work order created from this task.' });
      if (res.data.ticket_id) navigate(`/maintenance-tickets/${res.data.ticket_id}`);
    } catch {
      addFlash({ type: 'error', content: 'Failed to create a work order.' });
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error || !asset) {
    return <Alert type="error">{error || 'Asset not found.'}</Alert>;
  }

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Maintenance', href: '/maintenance' },
              { text: asset.name, href: `/maintenance/assets/${id}` },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Scheduled work, service history, cost and compliance for this asset."
            actions={
              <Button onClick={() => navigate(`/maintenance/${asset.category}`)}>
                Open category
              </Button>
            }
          >
            {asset.name}
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        {asset.is_regulatory && certDays != null && certDays < 30 && (
          <Alert type={certDays < 0 ? 'error' : 'warning'}>
            {certDays < 0
              ? `Certification expired ${Math.abs(certDays)} day(s) ago.`
              : `Certification expires in ${certDays} day(s).`}
          </Alert>
        )}

        <Container header={<Header variant="h2">At a glance</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            <ValuePair label="Status" value={<Badge>{asset.status}</Badge>} />
            <ValuePair
              label="Scheduled tasks"
              value={
                <StatusIndicator type={overdueCount > 0 ? 'error' : 'success'}>
                  {tasks.length} total{overdueCount > 0 ? ` · ${overdueCount} overdue` : ''}
                </StatusIndicator>
              }
            />
            <ValuePair label="Lifetime service cost" value={money(lifetimeCost)} />
            <ValuePair
              label="Certification expiry"
              value={
                asset.certification_expiry ? (
                  <StatusIndicator
                    type={certDays == null ? 'info' : certDays < 0 ? 'error' : certDays < 30 ? 'warning' : 'success'}
                  >
                    {date(asset.certification_expiry)}
                  </StatusIndicator>
                ) : null
              }
            />
          </ColumnLayout>
        </Container>

        <Container header={<Header variant="h2">Asset details</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            <ValuePair label="Category" value={asset.category} />
            <ValuePair label="Subtopic" value={asset.subtopic} />
            <ValuePair
              label="Property"
              value={
                asset.office ? (
                  <Link
                    onFollow={(e) => {
                      e.preventDefault();
                      if (asset.office_id) navigate(`/offices/${asset.office_id}`);
                    }}
                    href={asset.office_id ? `/offices/${asset.office_id}` : undefined}
                  >
                    {asset.office.location_name}
                  </Link>
                ) : null
              }
            />
            <ValuePair
              label="Servicing vendor"
              value={
                asset.vendor ? (
                  <Link
                    onFollow={(e) => {
                      e.preventDefault();
                      if (asset.vendor_id) navigate(`/vendors/${asset.vendor_id}`);
                    }}
                    href={asset.vendor_id ? `/vendors/${asset.vendor_id}` : undefined}
                  >
                    {asset.vendor.company_name}
                  </Link>
                ) : null
              }
            />
            <ValuePair label="Location" value={asset.location_desc} />
            <ValuePair label="Make" value={asset.make} />
            <ValuePair label="Model" value={asset.model} />
            <ValuePair label="Serial number" value={asset.serial_number} />
            <ValuePair label="Installed" value={date(asset.install_date)} />
            <ValuePair
              label="Regulatory"
              value={asset.is_regulatory ? 'Code-mandated' : 'Not regulatory'}
            />
          </ColumnLayout>
        </Container>

        <Table<MaintenanceTask>
          variant="container"
          items={tasks}
          header={
            <Header variant="h2" counter={`(${tasks.length})`}>
              Scheduled maintenance
            </Header>
          }
          columnDefinitions={[
            { id: 'title', header: 'Task', cell: (t) => t.title },
            { id: 'frequency', header: 'Frequency', cell: (t) => t.frequency || '—' },
            { id: 'last', header: 'Last completed', cell: (t) => date(t.last_completed_date) },
            {
              id: 'next',
              header: 'Next due',
              cell: (t) => (
                <StatusIndicator type={taskStatus(t)}>{date(t.next_due_date)}</StatusIndicator>
              ),
            },
            {
              id: 'vendor',
              header: 'Vendor',
              cell: (t) => t.vendor?.company_name || '—',
            },
            ...(canEdit
              ? [
                  {
                    id: 'actions',
                    header: 'Actions',
                    cell: (t: MaintenanceTask) => (
                      <Button variant="inline-link" onClick={() => generateWorkOrder(t)}>
                        Create work order
                      </Button>
                    ),
                  },
                ]
              : []),
          ]}
          empty={
            <Box textAlign="center" padding="m">
              No scheduled maintenance for this asset.
            </Box>
          }
        />

        <Table<MaintenanceLog>
          variant="container"
          items={logs}
          header={
            <Header
              variant="h2"
              counter={`(${logs.length})`}
              description={logs.length ? `Lifetime cost ${money(lifetimeCost)}` : undefined}
            >
              Service history
            </Header>
          }
          columnDefinitions={[
            { id: 'date', header: 'Date', cell: (l) => date(l.service_date) },
            { id: 'description', header: 'Work performed', cell: (l) => l.description },
            {
              id: 'by',
              header: 'Performed by',
              cell: (l) => l.vendor?.company_name || l.performed_by || '—',
            },
            { id: 'cost', header: 'Cost', cell: (l) => money(l.cost) },
            { id: 'invoice', header: 'Invoice', cell: (l) => l.invoice_number || '—' },
          ]}
          empty={
            <Box textAlign="center" padding="m">
              No service recorded for this asset.
            </Box>
          }
        />

        {asset.notes && (
          <Container header={<Header variant="h2">Notes</Header>}>
            <Box>
              <span style={{ whiteSpace: 'pre-wrap' }}>{asset.notes}</span>
            </Box>
          </Container>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default AssetDetailPage;
