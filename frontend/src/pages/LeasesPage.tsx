import React, { useState, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Pagination from '@cloudscape-design/components/pagination';
import CollectionPreferences from '@cloudscape-design/components/collection-preferences';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import PropertyFilter from '@cloudscape-design/components/property-filter';
import type { PropertyFilterProps } from '@cloudscape-design/components/property-filter';
import Alert from '@cloudscape-design/components/alert';
import Link from '@cloudscape-design/components/link';
import { leases as leasesApi } from '@/api';
import type { Lease } from '@/types';
import { usePreferences } from '@/context/PreferencesContext';
import { useFilterOptions } from '@/hooks/useFilterOptions';
import type { FilterOptionSpec } from '@/hooks/useFilterOptions';
import { useServerCollection } from '@/hooks/useServerCollection';
import ImportModal from '@/components/common/ImportModal';
import SavedFiltersDropdown from '@/components/common/SavedFiltersDropdown';
import { useAttachmentCounts } from '@/hooks/useAttachmentCounts';
import { LEASE_STATUS_OPTIONS, leaseStatusLabel } from '@/constants/leaseStatus';
import { useAuth } from '@/auth/AuthContext';
import { canMutateOperationalData } from '@/auth/permissions';

const DEFAULT_VISIBLE = [
  'lease_name',
  'office_location',
  'lessor_name',
  'expiration_date',
  'notice_period_days',
  'manager_name',
  'lease_year',
  'status',
  'attachments',
];

function daysUntil(dateStr?: string): number | null {
  if (!dateStr) return null;
  return Math.floor((new Date(dateStr).getTime() - Date.now()) / 86_400_000);
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString();
}

const FILTERING_PROPERTIES: PropertyFilterProps.FilteringProperty[] = [
  {
    key: 'year',
    operators: ['='],
    propertyLabel: 'Lease Year',
    groupValuesLabel: 'Lease Years',
  },
  {
    key: 'status',
    operators: ['='],
    propertyLabel: 'Status',
    groupValuesLabel: 'Statuses',
  },
  {
    key: 'manager_id',
    operators: ['='],
    propertyLabel: 'Manager',
    groupValuesLabel: 'Managers',
  },
  {
    key: 'notice_status',
    operators: ['='],
    propertyLabel: 'Notice',
    groupValuesLabel: 'Notice statuses',
  },
];

const FILTER_OPTION_SPECS: FilterOptionSpec[] = [
  { propertyKey: 'manager_id', source: 'manager' },
  {
    propertyKey: 'status',
    values: LEASE_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label })),
  },
  {
    propertyKey: 'notice_status',
    values: [
      { value: 'given', label: 'Given' },
      { value: 'not_given', label: 'Not given' },
    ],
  },
];

const LeasesPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = canMutateOperationalData(user?.role);
  const [searchParams, setSearchParams] = useSearchParams();
  const { getPageSize, setPageSize, getVisibleColumns, setVisibleColumns } = usePreferences();
  const visibleContent = getVisibleColumns('leases') ?? DEFAULT_VISIBLE;
  const [showImport, setShowImport] = useState(false);

  // Read virtual filters from URL
  const urlExpiringSoon = searchParams.get('expiring_soon');
  const urlOverdueNotices = searchParams.get('overdue_notices');
  const urlExpirationYear = searchParams.get('expiration_year');
  const hasActiveUrlFilter = !!(urlExpiringSoon || urlOverdueNotices || urlExpirationYear);

  const [filterQuery, setFilterQuery] = useState<PropertyFilterProps.Query>({
    tokens: [],
    operation: 'and',
  });

  // Combine URL filters + PropertyFilter tokens into server params
  const { filteringOptions, tokensToParams } = useFilterOptions(FILTER_OPTION_SPECS);
  const filters = useMemo(() => {
    // Tokens first so an explicit filter overrides the URL quick-filter.
    const params: Record<string, unknown> = {
      ...(urlExpiringSoon ? { expiring_within_days: parseInt(urlExpiringSoon, 10) || 90 } : {}),
      ...(urlOverdueNotices === 'true' ? { notice_status: 'not_given' } : {}),
      ...(urlExpirationYear ? { year: parseInt(urlExpirationYear, 10) } : {}),
      ...tokensToParams(filterQuery.tokens),
    };
    return params;
  }, [filterQuery, urlExpiringSoon, urlOverdueNotices, urlExpirationYear, tokensToParams]);

  const {
    items,
    total,
    loading,
    error,
    paginationProps,
    sortingColumn,
    sortingDescending,
    onSortingChange,
    refresh,
  } = useServerCollection<Lease>({
    fetchFn: leasesApi.list,
    pageKey: 'leases',
    defaultSortField: 'lease_expiration',
    filters,
  });

  const attachmentCounts = useAttachmentCounts(
    'lease',
    items.map((l) => l.id),
  );

  const columnDefinitions = [
    {
      id: 'lease_name',
      header: 'Lease Name',
      cell: (item: Lease) => item.lease_name,
      sortingField: 'lease_name',
    },
    {
      id: 'office_location',
      header: 'Office',
      cell: (item: Lease) => item.office?.location_name || '—',
    },
    {
      id: 'lessor_name',
      header: 'Lessor',
      cell: (item: Lease) => item.lessor_name || '—',
      sortingField: 'lessor_name',
    },
    {
      id: 'expiration_date',
      header: 'Expiration Date',
      cell: (item: Lease) => {
        const days = daysUntil(item.lease_expiration);
        if (days === null) return <Box>—</Box>;
        const type = days < 90 ? 'error' : days < 180 ? 'warning' : 'success';
        return (
          <StatusIndicator type={type}>{formatDate(item.lease_expiration)}</StatusIndicator>
        );
      },
      sortingField: 'lease_expiration',
    },
    {
      id: 'notice_period_days',
      header: 'Notice (days)',
      cell: (item: Lease) => item.notice_period_days ?? '—',
    },
    {
      id: 'manager_name',
      header: 'Manager',
      cell: (item: Lease) => item.manager?.name || '—',
    },
    {
      id: 'lease_year',
      header: 'Lease Year',
      cell: (item: Lease) => item.expiration_year ?? '—',
      sortingField: 'expiration_year',
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item: Lease) => leaseStatusLabel(item.status) || '—',
      sortingField: 'status',
    },
    {
      id: 'attachments',
      header: 'Attachments',
      cell: (item: Lease) => attachmentCounts[item.id] ?? 0,
      width: 120,
    },
  ];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <SavedFiltersDropdown
                entity="leases"
                currentQuery={filterQuery}
                onApply={setFilterQuery}
              />
              <Button onClick={refresh} iconName="refresh" />
              {canEdit && <Button iconName="upload" onClick={() => setShowImport(true)}>Import</Button>}
              <Button iconName="calendar" onClick={() => navigate('/leases/calendar')}>Calendar</Button>
              <Button
                iconName="download"
                onClick={async () => {
                  const res = await leasesApi.exportCsv();
                  const url = window.URL.createObjectURL(new Blob([res.data]));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'leases.csv';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export CSV
              </Button>
              <Button
                iconName="calendar"
                onClick={async () => {
                  const res = await leasesApi.exportIcal();
                  const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/calendar' }));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'lease-deadlines.ics';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export to Calendar (.ics)
              </Button>
              {canEdit && (
                <Button variant="primary" onClick={() => navigate('/leases/wizard')}>
                  Create lease
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Leases
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible>
            {error}
          </Alert>
        )}
        {hasActiveUrlFilter && (
          <Alert type="info" dismissible onDismiss={() => setSearchParams({}, { replace: true })}>
            Showing filtered results.{' '}
            <Link onFollow={() => setSearchParams({}, { replace: true })}>Clear filter</Link>
          </Alert>
        )}
        <SpaceBetween direction="horizontal" size="xs">
          <Button
            variant={urlExpiringSoon === '90' ? 'primary' : 'normal'}
            onClick={() => setSearchParams({ expiring_soon: '90' }, { replace: true })}
          >
            Expiring This Quarter
          </Button>
          <Button
            variant={urlOverdueNotices === 'true' ? 'primary' : 'normal'}
            onClick={() => setSearchParams({ overdue_notices: 'true' }, { replace: true })}
          >
            Overdue Notices
          </Button>
          {hasActiveUrlFilter && (
            <Button onClick={() => setSearchParams({}, { replace: true })}>Show All</Button>
          )}
        </SpaceBetween>
        <Table
          loading={loading}
          loadingText="Loading leases..."
          columnDefinitions={columnDefinitions}
          visibleColumns={visibleContent}
          items={items}
          sortingColumn={sortingColumn}
          sortingDescending={sortingDescending}
          onSortingChange={onSortingChange}
          onRowClick={({ detail }) => navigate(`/leases/${detail.item.id}`)}
          filter={
            <PropertyFilter
              query={filterQuery}
              onChange={({ detail }) => setFilterQuery(detail)}
              filteringProperties={FILTERING_PROPERTIES}
              filteringOptions={filteringOptions}
              countText={`${total} matches`}
              expandToViewport
            />
          }
          pagination={<Pagination {...paginationProps} />}
          preferences={
            <CollectionPreferences
              title="Preferences"
              confirmLabel="Confirm"
              cancelLabel="Cancel"
              preferences={{ pageSize: getPageSize('leases'), visibleContent }}
              onConfirm={({ detail }) => {
                if (detail.pageSize) setPageSize('leases', detail.pageSize);
                if (detail.visibleContent) setVisibleColumns('leases', detail.visibleContent as string[]);
              }}
              pageSizePreference={{
                title: 'Page size',
                options: [
                  { value: 10, label: '10 leases' },
                  { value: 20, label: '20 leases' },
                  { value: 50, label: '50 leases' },
                ],
              }}
              visibleContentPreference={{
                title: 'Select visible content',
                options: [
                  {
                    label: 'Lease fields',
                    options: columnDefinitions.map((col) => ({
                      id: col.id,
                      label: col.header as string,
                    })),
                  },
                ],
              }}
            />
          }
          header={
            <Header counter={loading ? undefined : `(${total})`}>Leases</Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No leases</b>
                {canEdit && (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button variant="primary" onClick={() => navigate('/leases/wizard')}>Create lease</Button>
                  </SpaceBetween>
                )}
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>
      {canEdit && <ImportModal
        visible={showImport}
        onDismiss={() => setShowImport(false)}
        entityName="leases"
        entityLabel="Leases"
        onComplete={refresh}
      />}
    </ContentLayout>
  );
};

export default LeasesPage;
