import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
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
import { offices as officesApi } from '@/api';
import type { Office } from '@/types';
import { usePreferences } from '@/context/PreferencesContext';
import { useServerCollection } from '@/hooks/useServerCollection';
import ImportModal from '@/components/common/ImportModal';
import SavedFiltersDropdown from '@/components/common/SavedFiltersDropdown';

const DEFAULT_VISIBLE = ['pinned', 'office_number', 'location_name', 'location_type', 'city', 'state', 'phone_number', 'manager', 'is_active'];

const FILTERING_PROPERTIES: PropertyFilterProps.FilteringProperty[] = [
  { key: 'region_number', operators: ['=', ':'], propertyLabel: 'Region', groupValuesLabel: 'Regions' },
  { key: 'location_type', operators: ['=', ':'], propertyLabel: 'Type', groupValuesLabel: 'Types' },
  { key: 'sector', operators: ['=', ':'], propertyLabel: 'Sector', groupValuesLabel: 'Sectors' },
  { key: 'state', operators: ['=', ':'], propertyLabel: 'State', groupValuesLabel: 'States' },
];

const OfficesPage: React.FC = () => {
  const navigate = useNavigate();
  const { getPageSize, setPageSize, getVisibleColumns, setVisibleColumns, getPinnedOffices, togglePinnedOffice } = usePreferences();
  const visibleContent = getVisibleColumns('offices') ?? DEFAULT_VISIBLE;
  const [showImport, setShowImport] = useState(false);
  const pinnedOffices = getPinnedOffices();

  const [filterQuery, setFilterQuery] = useState<PropertyFilterProps.Query>({
    tokens: [],
    operation: 'and',
  });

  // Convert PropertyFilter tokens to server query params
  const filters = useMemo(() => {
    const params: Record<string, unknown> = {};
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
  } = useServerCollection<Office>({
    fetchFn: officesApi.list,
    pageKey: 'offices',
    defaultSortField: 'office_number',
    filters,
  });

  const isPinned = (id: string) => pinnedOffices.some((o) => o.id === id);

  const columnDefinitions = [
    {
      id: 'pinned',
      header: '',
      cell: (item: Office) => (
        <span
          role="button"
          tabIndex={0}
          style={{ cursor: 'pointer', fontSize: '16px', color: isPinned(item.id) ? '#0972d3' : '#aab7b8' }}
          onClick={(e) => {
            e.stopPropagation();
            const label = item.location_name || `Office #${item.office_number}`;
            togglePinnedOffice(item.id, label);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              e.stopPropagation();
              const label = item.location_name || `Office #${item.office_number}`;
              togglePinnedOffice(item.id, label);
            }
          }}
          aria-label={isPinned(item.id) ? 'Unpin office' : 'Pin office'}
          title={isPinned(item.id) ? 'Unpin office' : 'Pin office'}
        >
          {isPinned(item.id) ? '\u2605' : '\u2606'}
        </span>
      ),
      width: 50,
    },
    {
      id: 'office_number',
      header: 'Office #',
      cell: (item: Office) => item.office_number,
      sortingField: 'office_number',
    },
    {
      id: 'location_name',
      header: 'Location',
      cell: (item: Office) => item.location_name,
      sortingField: 'location_name',
    },
    {
      id: 'location_type',
      header: 'Type',
      cell: (item: Office) => item.location_type,
      sortingField: 'location_type',
    },
    {
      id: 'city',
      header: 'City',
      cell: (item: Office) => item.city || '—',
      sortingField: 'city',
    },
    {
      id: 'state',
      header: 'State',
      cell: (item: Office) => item.state || '—',
      sortingField: 'state',
    },
    {
      id: 'phone_number',
      header: 'Phone',
      cell: (item: Office) => item.phone_number || '—',
    },
    {
      id: 'manager',
      header: 'Manager',
      cell: (item: Office) => item.manager?.name || '—',
    },
    {
      id: 'is_active',
      header: 'Active',
      cell: (item: Office) => (
        <StatusIndicator type={item.is_active ? 'success' : 'stopped'}>
          {item.is_active ? 'Active' : 'Inactive'}
        </StatusIndicator>
      ),
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
                entity="offices"
                currentQuery={filterQuery}
                onApply={setFilterQuery}
              />
              <Button onClick={refresh} iconName="refresh" />
              <Button iconName="upload" onClick={() => setShowImport(true)}>Import</Button>
              <Button variant="primary" onClick={() => navigate('/offices/new')}>
                Create Office
              </Button>
            </SpaceBetween>
          }
        >
          Offices
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible>
            {error}
          </Alert>
        )}
        <Table
          loading={loading}
          loadingText="Loading offices..."
          columnDefinitions={columnDefinitions}
          visibleColumns={visibleContent}
          items={items}
          sortingColumn={sortingColumn}
          sortingDescending={sortingDescending}
          onSortingChange={onSortingChange}
          onRowClick={({ detail }) => navigate(`/offices/${detail.item.id}`)}
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
              preferences={{ pageSize: getPageSize('offices'), visibleContent }}
              onConfirm={({ detail }) => {
                if (detail.pageSize) setPageSize('offices', detail.pageSize);
                if (detail.visibleContent) setVisibleColumns('offices', detail.visibleContent as string[]);
              }}
              pageSizePreference={{
                title: 'Page size',
                options: [
                  { value: 10, label: '10 offices' },
                  { value: 20, label: '20 offices' },
                  { value: 50, label: '50 offices' },
                ],
              }}
              visibleContentPreference={{
                title: 'Select visible content',
                options: [
                  {
                    label: 'Office fields',
                    options: columnDefinitions
                      .filter((col) => col.id !== 'pinned')
                      .map((col) => ({
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
              Offices
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No offices</b>
                <Button onClick={() => navigate('/offices/new')}>Create office</Button>
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>
      <ImportModal
        visible={showImport}
        onDismiss={() => setShowImport(false)}
        entityName="offices"
        entityLabel="Offices"
        onComplete={refresh}
      />
    </ContentLayout>
  );
};

export default OfficesPage;
