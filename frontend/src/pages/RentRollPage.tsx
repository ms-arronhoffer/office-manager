import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Table from '@cloudscape-design/components/table';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Select from '@cloudscape-design/components/select';
import FormField from '@cloudscape-design/components/form-field';
import Link from '@cloudscape-design/components/link';
import { leases as leasesApi, managers as managersApi } from '@/api';
import type { RentRollRow, RentRollResponse, Manager } from '@/types';

const EXPIRY_OPTIONS = [
  { value: '', label: 'All' },
  { value: '90', label: 'Expiring within 90 days' },
  { value: '180', label: 'Expiring within 180 days' },
  { value: '365', label: 'Expiring within 1 year' },
];

function formatCurrency(value: number, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(value);
}

function expirationStatus(days?: number): 'error' | 'warning' | 'info' | undefined {
  if (days == null) return undefined;
  if (days < 0) return 'error';
  if (days <= 90) return 'error';
  if (days <= 180) return 'warning';
  return 'info';
}

function downloadCsv(rows: RentRollRow[], total_monthly: number, total_annual: number) {
  const headers = ['Lease Name', 'Office', 'Lessor', 'Monthly Rent', 'Annual Rent', 'Escalation %', 'Expiration', 'Days Remaining', 'Classification', 'Currency', 'Manager'];
  const csvRows = rows.map(r => [
    r.lease_name,
    r.office_name ?? '',
    r.lessor_name ?? '',
    r.monthly_rent,
    r.annual_rent,
    r.annual_escalation_rate != null ? `${(r.annual_escalation_rate * 100).toFixed(2)}%` : '',
    r.lease_expiration ?? '',
    r.days_to_expiration ?? '',
    r.lease_classification ?? '',
    r.currency,
    r.manager_name ?? '',
  ]);
  csvRows.push(['TOTALS', '', '', total_monthly, total_annual, '', '', '', '', '', '']);

  const content = [headers, ...csvRows]
    .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([content], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'rent-roll.csv';
  a.click();
  URL.revokeObjectURL(url);
}

const RentRollPage: React.FC = () => {
  const navigate = useNavigate();
  const [data, setData] = useState<RentRollResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [managers, setManagers] = useState<Manager[]>([]);
  const [selectedManager, setSelectedManager] = useState<{ value: string; label: string } | null>(null);
  const [selectedExpiry, setSelectedExpiry] = useState<{ value: string; label: string }>(EXPIRY_OPTIONS[0]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, unknown> = {};
      if (selectedManager?.value) params.manager_id = selectedManager.value;
      if (selectedExpiry?.value) params.expiring_within_days = parseInt(selectedExpiry.value);
      const res = await leasesApi.rentRoll(params);
      setData(res.data);
    } catch {
      setError('Failed to load rent roll data.');
    } finally {
      setLoading(false);
    }
  }, [selectedManager, selectedExpiry]);

  useEffect(() => {
    managersApi.list().then(res => setManagers(res.data)).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const expiringIn90 = data?.rows.filter(r => r.days_to_expiration != null && r.days_to_expiration >= 0 && r.days_to_expiration <= 90).length ?? 0;
  const expiringIn180 = data?.rows.filter(r => r.days_to_expiration != null && r.days_to_expiration >= 0 && r.days_to_expiration <= 180).length ?? 0;
  const expiringIn365 = data?.rows.filter(r => r.days_to_expiration != null && r.days_to_expiration >= 0 && r.days_to_expiration <= 365).length ?? 0;

  const managerOptions = [
    { value: '', label: 'All Managers' },
    ...managers.map(m => ({ value: m.id, label: m.name })),
  ];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          actions={
            <Button
              iconName="download"
              disabled={!data || data.rows.length === 0}
              onClick={() => data && downloadCsv(data.rows, data.total_monthly, data.total_annual)}
            >
              Export CSV
            </Button>
          }
        >
          Rent Roll
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && <Alert type="error">{error}</Alert>}

        {/* KPI tiles */}
        {data && (
          <Container header={<Header variant="h2">Portfolio Summary</Header>}>
            <ColumnLayout columns={5} variant="text-grid">
              <div>
                <Box variant="awsui-key-label">Leases with Rent Data</Box>
                <Box fontSize="display-l" fontWeight="bold">{data.count}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Total Monthly Obligation</Box>
                <Box fontSize="display-l" fontWeight="bold">{formatCurrency(data.total_monthly)}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Total Annual Obligation</Box>
                <Box fontSize="display-l" fontWeight="bold">{formatCurrency(data.total_annual)}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Expiring in 90 Days</Box>
                <Box>
                  <StatusIndicator type={expiringIn90 > 0 ? 'error' : 'success'}>
                    {expiringIn90} lease{expiringIn90 !== 1 ? 's' : ''}
                  </StatusIndicator>
                </Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Expiring in 365 Days</Box>
                <Box>
                  <StatusIndicator type={expiringIn365 > 3 ? 'warning' : 'success'}>
                    {expiringIn365} lease{expiringIn365 !== 1 ? 's' : ''}
                    {expiringIn180 !== expiringIn365 && ` (${expiringIn180} in 180d)`}
                  </StatusIndicator>
                </Box>
              </div>
            </ColumnLayout>
          </Container>
        )}

        {/* Filters */}
        <Container header={<Header variant="h2">Filters</Header>}>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Manager">
              <Select
                selectedOption={selectedManager ?? { value: '', label: 'All Managers' }}
                onChange={({ detail }) => setSelectedManager(detail.selectedOption.value ? detail.selectedOption as { value: string; label: string } : null)}
                options={managerOptions}
              />
            </FormField>
            <FormField label="Expiration Window">
              <Select
                selectedOption={selectedExpiry}
                onChange={({ detail }) => setSelectedExpiry(detail.selectedOption as { value: string; label: string })}
                options={EXPIRY_OPTIONS}
              />
            </FormField>
          </SpaceBetween>
        </Container>

        {/* Rent Roll Table */}
        {loading ? (
          <Box textAlign="center" padding={{ top: 'xxxl' }}>
            <Spinner size="large" />
          </Box>
        ) : (
          <Table
            header={
              <Header
                variant="h2"
                counter={`(${data?.count ?? 0})`}
                description={data ? `Monthly: ${formatCurrency(data.total_monthly)} | Annual: ${formatCurrency(data.total_annual)}` : undefined}
              >
                Rent Roll
              </Header>
            }
            columnDefinitions={[
              {
                id: 'lease_name',
                header: 'Lease',
                cell: (r: RentRollRow) => (
                  <Link onFollow={() => navigate(`/leases/${r.lease_id}`)}>{r.lease_name}</Link>
                ),
                sortingField: 'lease_name',
              },
              {
                id: 'office_name',
                header: 'Office',
                cell: (r: RentRollRow) =>
                  r.office_id ? (
                    <Link onFollow={() => navigate(`/offices/${r.office_id}`)}>{r.office_name ?? '—'}</Link>
                  ) : (r.office_name ?? '—'),
                sortingField: 'office_name',
              },
              {
                id: 'lessor_name',
                header: 'Lessor',
                cell: (r: RentRollRow) => r.lessor_name ?? '—',
                sortingField: 'lessor_name',
              },
              {
                id: 'monthly_rent',
                header: 'Monthly Rent',
                cell: (r: RentRollRow) => formatCurrency(r.monthly_rent, r.currency),
                sortingField: 'monthly_rent',
              },
              {
                id: 'annual_rent',
                header: 'Annual Rent',
                cell: (r: RentRollRow) => formatCurrency(r.annual_rent, r.currency),
                sortingField: 'annual_rent',
              },
              {
                id: 'escalation',
                header: 'Escalation',
                cell: (r: RentRollRow) =>
                  r.annual_escalation_rate != null ? `${(r.annual_escalation_rate * 100).toFixed(2)}%` : '—',
              },
              {
                id: 'expiration',
                header: 'Expiration',
                cell: (r: RentRollRow) => {
                  if (!r.lease_expiration) return '—';
                  const st = expirationStatus(r.days_to_expiration);
                  const label = new Date(r.lease_expiration).toLocaleDateString();
                  return st ? <StatusIndicator type={st}>{label}</StatusIndicator> : label;
                },
                sortingField: 'lease_expiration',
              },
              {
                id: 'days',
                header: 'Days Remaining',
                cell: (r: RentRollRow) => r.days_to_expiration != null ? r.days_to_expiration : '—',
                sortingField: 'days_to_expiration',
              },
              {
                id: 'classification',
                header: 'Type',
                cell: (r: RentRollRow) => r.lease_classification ?? '—',
              },
              {
                id: 'manager',
                header: 'Manager',
                cell: (r: RentRollRow) => r.manager_name ?? '—',
              },
            ]}
            items={data?.rows ?? []}
            sortingDisabled={false}
            empty={
              <Box textAlign="center" color="inherit" padding="l">
                No leases with rent data found.
              </Box>
            }
          />
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default RentRollPage;
