import React, { useState, useMemo, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Pagination from '@cloudscape-design/components/pagination';
import PropertyFilter from '@cloudscape-design/components/property-filter';
import type { PropertyFilterProps } from '@cloudscape-design/components/property-filter';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';
import Alert from '@cloudscape-design/components/alert';
import Tabs from '@cloudscape-design/components/tabs';
import CollectionPreferences from '@cloudscape-design/components/collection-preferences';
import Select from '@cloudscape-design/components/select';
import { maintenanceTickets as ticketsApi } from '@/api';
import type { MaintenanceTicket } from '@/types';
import { useAuth } from '@/auth/AuthContext';
import { usePreferences } from '@/context/PreferencesContext';
import { useSiteSettings } from '@/context/SiteSettingsContext';
import { useServerCollection } from '@/hooks/useServerCollection';
import SavedFiltersDropdown from '@/components/common/SavedFiltersDropdown';

const DEFAULT_VISIBLE = ['subject', 'priority', 'status', 'category', 'office', 'assigned_to', 'created_by', 'created_at', 'days_open'];

function daysOpen(createdAt?: string): number {
  if (!createdAt) return 0;
  return Math.floor((Date.now() - new Date(createdAt).getTime()) / 86_400_000);
}

const capitalize = (s: string) =>
  s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');

const statusIndicatorType = (
  status: string
): 'success' | 'in-progress' | 'pending' => {
  switch (status) {
    case 'closed':
      return 'success';
    case 'in_progress':
      return 'in-progress';
    default:
      return 'pending';
  }
};

const priorityBadgeColor = (priority: string): 'blue' | 'grey' | 'red' => {
  switch (priority) {
    case 'high':
      return 'red';
    case 'medium':
      return 'blue';
    default:
      return 'grey';
  }
};

const STATUS_OPTIONS = [
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'closed', label: 'Closed' },
];

const FILTERING_PROPERTIES: PropertyFilterProps.FilteringProperty[] = [
  { key: 'priority', operators: ['='], propertyLabel: 'Priority', groupValuesLabel: 'Priorities' },
];

const MaintenanceTicketsPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { settings } = useSiteSettings();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const SLA_DAYS = {
    high: settings.sla_high_days ?? 1,
    medium: settings.sla_medium_days ?? 3,
    low: settings.sla_low_days ?? 7,
  };

  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('status') || 'all';
  const [selectedItems, setSelectedItems] = useState<MaintenanceTicket[]>([]);
  const [bulkStatus, setBulkStatus] = useState<{ value: string; label: string } | null>(null);
  const { getPageSize, setPageSize: savePrefPageSize, getVisibleColumns, setVisibleColumns } = usePreferences();
  const visibleContent = getVisibleColumns('maintenance-tickets') ?? DEFAULT_VISIBLE;

  const [filterQuery, setFilterQuery] = useState<PropertyFilterProps.Query>({
    tokens: [],
    operation: 'and',
  });

  // Combine tab filter + PropertyFilter tokens
  const filters = useMemo(() => {
    const params: Record<string, unknown> = {};

    // Tab status filter
    if (activeTab !== 'all') {
      params.status = activeTab;
    }

    // PropertyFilter tokens
    for (const token of filterQuery.tokens) {
      if ('propertyKey' in token && token.propertyKey && token.value) {
        params[token.propertyKey] = token.value;
      }
    }
    return params;
  }, [filterQuery, activeTab]);

  const {
    items,
    total,
    loading,
    paginationProps,
    sortingColumn,
    sortingDescending,
    onSortingChange,
    refresh,
  } = useServerCollection<MaintenanceTicket>({
    fetchFn: ticketsApi.list,
    pageKey: 'maintenance-tickets',
    defaultSortField: 'created_at',
    defaultSortDescending: true,
    filters,
  });

  const handleInlineStatusChange = useCallback(async (ticketId: string, newStatus: string) => {
    try {
      await ticketsApi.update(ticketId, { status: newStatus });
      refresh();
    } catch {
      setError('Failed to update status.');
    }
  }, [refresh]);

  const handleBulkStatusChange = useCallback(async (newStatus: string) => {
    if (selectedItems.length === 0) return;
    try {
      await ticketsApi.bulkUpdate({ ids: selectedItems.map((t) => t.id), status: newStatus });
      setSelectedItems([]);
      refresh();
    } catch {
      setError('Failed to bulk update tickets.');
    }
  }, [selectedItems, refresh]);

  const columnDefinitions = [
    {
      id: 'subject',
      header: 'Subject',
      cell: (item: MaintenanceTicket) => item.subject,
      sortingField: 'subject',
    },
    {
      id: 'priority',
      header: 'Priority',
      cell: (item: MaintenanceTicket) => (
        <Badge color={priorityBadgeColor(item.priority)}>
          {capitalize(item.priority)}
        </Badge>
      ),
      sortingField: 'priority',
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item: MaintenanceTicket) =>
        canEdit ? (
          <Select
            selectedOption={STATUS_OPTIONS.find((o) => o.value === item.status) || null}
            options={STATUS_OPTIONS}
            onChange={({ detail }) => {
              if (detail.selectedOption.value) {
                handleInlineStatusChange(item.id, detail.selectedOption.value);
              }
            }}
            expandToViewport
          />
        ) : (
          <StatusIndicator type={statusIndicatorType(item.status)}>
            {capitalize(item.status)}
          </StatusIndicator>
        ),
      sortingField: 'status',
    },
    {
      id: 'category',
      header: 'Category',
      cell: (item: MaintenanceTicket) => item.category?.name || '—',
    },
    {
      id: 'office',
      header: 'Office',
      cell: (item: MaintenanceTicket) => item.office?.location_name || '—',
    },
    {
      id: 'assigned_to',
      header: 'Assigned To',
      cell: (item: MaintenanceTicket) => item.assigned_to?.name || '—',
    },
    {
      id: 'created_by',
      header: 'Created By',
      cell: (item: MaintenanceTicket) => item.created_by?.display_name || '—',
    },
    {
      id: 'created_at',
      header: 'Created',
      cell: (item: MaintenanceTicket) =>
        item.created_at ? new Date(item.created_at).toLocaleDateString() : '—',
      sortingField: 'created_at',
    },
    {
      id: 'days_open',
      header: 'Days Open',
      cell: (item: MaintenanceTicket) => {
        if (item.status === 'closed') return <StatusIndicator type="success">Closed</StatusIndicator>;
        const d = daysOpen(item.created_at);
        const sla = SLA_DAYS[item.priority] ?? 7;
        const breached = d > sla;
        return (
          <StatusIndicator type={breached ? 'error' : 'success'}>
            {d}d
          </StatusIndicator>
        );
      },
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
                entity="maintenance-tickets"
                currentQuery={filterQuery}
                onApply={setFilterQuery}
              />
              <Button iconName="refresh" onClick={refresh} />
              <Button
                iconName="download"
                onClick={async () => {
                  const res = await ticketsApi.exportCsv();
                  const url = window.URL.createObjectURL(new Blob([res.data]));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'maintenance-tickets.csv';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export CSV
              </Button>
              {canEdit && (
                <Button variant="primary" onClick={() => navigate('/maintenance-tickets/new')}>
                  Create Ticket
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Maintenance Tickets
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        <Tabs
          activeTabId={activeTab}
          onChange={({ detail }) => {
            setSelectedItems([]);
            if (detail.activeTabId === 'all') {
              setSearchParams({}, { replace: true });
            } else {
              setSearchParams({ status: detail.activeTabId }, { replace: true });
            }
          }}
          tabs={[
            { id: 'all', label: 'All' },
            { id: 'open', label: 'Open' },
            { id: 'in_progress', label: 'In Progress' },
            { id: 'closed', label: 'Closed' },
          ]}
        />
        <Table
          loading={loading}
          loadingText="Loading tickets..."
          columnDefinitions={columnDefinitions}
          visibleColumns={visibleContent}
          items={items}
          sortingColumn={sortingColumn}
          sortingDescending={sortingDescending}
          onSortingChange={onSortingChange}
          selectionType={canEdit ? 'multi' : undefined}
          selectedItems={selectedItems}
          onSelectionChange={({ detail }) => setSelectedItems(detail.selectedItems as MaintenanceTicket[])}
          onRowClick={({ detail }) => navigate(`/maintenance-tickets/${detail.item.id}`)}
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
              preferences={{ pageSize: getPageSize('maintenance-tickets'), visibleContent }}
              onConfirm={({ detail }) => {
                if (detail.pageSize) savePrefPageSize('maintenance-tickets', detail.pageSize);
                if (detail.visibleContent) setVisibleColumns('maintenance-tickets', detail.visibleContent as string[]);
              }}
              pageSizePreference={{
                title: 'Page size',
                options: [
                  { value: 10, label: '10 tickets' },
                  { value: 20, label: '20 tickets' },
                  { value: 50, label: '50 tickets' },
                ],
              }}
              visibleContentPreference={{
                title: 'Select visible content',
                options: [
                  {
                    label: 'Ticket fields',
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
            <Header
              counter={loading ? undefined : `(${total})`}
              actions={
                canEdit && selectedItems.length > 0 ? (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Select
                      selectedOption={bulkStatus}
                      options={STATUS_OPTIONS}
                      placeholder="Change status to..."
                      onChange={({ detail }) => setBulkStatus(detail.selectedOption as { value: string; label: string })}
                      expandToViewport
                    />
                    <Button
                      disabled={!bulkStatus}
                      onClick={() => {
                        if (bulkStatus) {
                          handleBulkStatusChange(bulkStatus.value);
                          setBulkStatus(null);
                        }
                      }}
                    >
                      Apply to {selectedItems.length} selected
                    </Button>
                  </SpaceBetween>
                ) : undefined
              }
            >
              Maintenance Tickets
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No maintenance tickets found</b>
                {canEdit && (
                  <Button onClick={() => navigate('/maintenance-tickets/new')}>
                    Create ticket
                  </Button>
                )}
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default MaintenanceTicketsPage;
