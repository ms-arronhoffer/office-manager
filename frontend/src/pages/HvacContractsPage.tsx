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
import { hvacContracts as hvacContractsApi } from '@/api';
import type { HvacContract } from '@/types';
import { usePreferences } from '@/context/PreferencesContext';
import { useServerCollection } from '@/hooks/useServerCollection';
import ImportModal from '@/components/common/ImportModal';

const DEFAULT_VISIBLE = [
  'hvac_company',
  'office',
  'frequency',
  'next_service_date',
  'landlord_handles',
  'manager',
  'contact',
];

const formatDate = (dateStr?: string): string => {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
};

const FILTERING_PROPERTIES: PropertyFilterProps.FilteringProperty[] = [
  { key: 'landlord_handles', operators: ['='], propertyLabel: 'Landlord Handles', groupValuesLabel: 'Landlord Handles' },
  { key: 'frequency', operators: ['=', ':'], propertyLabel: 'Frequency', groupValuesLabel: 'Frequencies' },
];

const HvacContractsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { getPageSize, setPageSize, getVisibleColumns, setVisibleColumns } = usePreferences();
  const urlDueSoon = searchParams.get('due_soon');
  const visibleContent = getVisibleColumns('hvac-contracts') ?? DEFAULT_VISIBLE;
  const [showImport, setShowImport] = useState(false);

  const [filterQuery, setFilterQuery] = useState<PropertyFilterProps.Query>({
    tokens: [],
    operation: 'and',
  });

  const filters = useMemo(() => {
    const params: Record<string, unknown> = {};

    // PropertyFilter tokens
    for (const token of filterQuery.tokens) {
      if ('propertyKey' in token && token.propertyKey && token.value) {
        params[token.propertyKey] = token.value;
      } else if ('value' in token && token.value) {
        params.search = token.value;
      }
    }

    return params;
  }, [filterQuery]);

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
  } = useServerCollection<HvacContract>({
    fetchFn: hvacContractsApi.list,
    pageKey: 'hvac-contracts',
    defaultSortField: 'office_number',
    filters,
  });

  const columnDefinitions = [
    {
      id: 'hvac_company',
      header: 'Vendor',
      cell: (item: HvacContract) => item.hvac_company || '—',
      sortingField: 'hvac_company',
    },
    {
      id: 'office',
      header: 'Office',
      cell: (item: HvacContract) => item.office_name || '—',
      sortingField: 'office_name',
    },
    {
      id: 'frequency',
      header: 'Frequency',
      cell: (item: HvacContract) => item.frequency || '—',
      sortingField: 'frequency',
    },
    {
      id: 'next_service_date',
      header: 'Next Service Date',
      cell: (item: HvacContract) => formatDate(item.next_service_date),
      sortingField: 'next_service_date',
    },
    {
      id: 'landlord_handles',
      header: 'Landlord Handles',
      cell: (item: HvacContract) => (
        <StatusIndicator type={item.landlord_handles ? 'success' : 'stopped'}>
          {item.landlord_handles ? 'Yes' : 'No'}
        </StatusIndicator>
      ),
    },
    {
      id: 'manager',
      header: 'Manager',
      cell: (item: HvacContract) => item.manager?.name || '—',
    },
    {
      id: 'contact',
      header: 'Contact',
      cell: (item: HvacContract) => item.contact || '—',
    },
  ];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={refresh} iconName="refresh" />
              <Button iconName="upload" onClick={() => setShowImport(true)}>Import</Button>
              <Button
                iconName="download"
                onClick={async () => {
                  const res = await hvacContractsApi.exportCsv();
                  const url = window.URL.createObjectURL(new Blob([res.data]));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'hvac-contracts.csv';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export CSV
              </Button>
              <Button
                iconName="calendar"
                onClick={async () => {
                  const res = await hvacContractsApi.exportIcal();
                  const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/calendar' }));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'hvac-service-dates.ics';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export to Calendar (.ics)
              </Button>
              <Button variant="primary" onClick={() => navigate('/hvac-contracts/new')}>
                Create Contract
              </Button>
            </SpaceBetween>
          }
        >
          HVAC Contracts
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible>
            {error}
          </Alert>
        )}
        {urlDueSoon === 'true' && (
          <Alert type="info" dismissible onDismiss={() => setSearchParams({}, { replace: true })}>
            Showing contracts with service due within 30 days.{' '}
            <Link onFollow={() => setSearchParams({}, { replace: true })}>Show all</Link>
          </Alert>
        )}
        <Table
          loading={loading}
          loadingText="Loading HVAC contracts..."
          columnDefinitions={columnDefinitions}
          visibleColumns={visibleContent}
          items={items}
          sortingColumn={sortingColumn}
          sortingDescending={sortingDescending}
          onSortingChange={onSortingChange}
          onRowClick={({ detail }) => navigate(`/hvac-contracts/${detail.item.id}`)}
          filter={
            <PropertyFilter
              query={filterQuery}
              onChange={({ detail }) => setFilterQuery(detail)}
              filteringProperties={FILTERING_PROPERTIES}
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
              preferences={{ pageSize: getPageSize('hvac-contracts'), visibleContent }}
              onConfirm={({ detail }) => {
                if (detail.pageSize) setPageSize('hvac-contracts', detail.pageSize);
                if (detail.visibleContent) setVisibleColumns('hvac-contracts', detail.visibleContent as string[]);
              }}
              pageSizePreference={{
                title: 'Page size',
                options: [
                  { value: 10, label: '10 contracts' },
                  { value: 20, label: '20 contracts' },
                  { value: 50, label: '50 contracts' },
                ],
              }}
              visibleContentPreference={{
                title: 'Select visible content',
                options: [
                  {
                    label: 'Contract fields',
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
            <Header counter={loading ? undefined : `(${total})`}>
              HVAC Contracts
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No HVAC contracts</b>
                <Button onClick={() => navigate('/hvac-contracts/new')}>
                  Create contract
                </Button>
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>
      <ImportModal
        visible={showImport}
        onDismiss={() => setShowImport(false)}
        entityName="hvac-contracts"
        entityLabel="HVAC Contracts"
        onComplete={refresh}
      />
    </ContentLayout>
  );
};

export default HvacContractsPage;
