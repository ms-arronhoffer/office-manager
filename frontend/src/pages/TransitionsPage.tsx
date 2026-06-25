import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Pagination from '@cloudscape-design/components/pagination';
import PropertyFilter from '@cloudscape-design/components/property-filter';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import CollectionPreferences from '@cloudscape-design/components/collection-preferences';
import Alert from '@cloudscape-design/components/alert';
import { useCollection } from '@cloudscape-design/collection-hooks';
import { transitions as transitionsApi } from '@/api';
import type { Transition } from '@/types';
import { usePreferences } from '@/context/PreferencesContext';
import { useAuth } from '@/auth/AuthContext';
import ImportModal from '@/components/common/ImportModal';

const DEFAULT_VISIBLE = ['office', 'transition_type', 'status', 'start_date', 'target_date', 'checklist'];

const capitalize = (s: string) =>
  s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');

const statusIndicatorType = (
  status: Transition['status']
): 'success' | 'in-progress' | 'pending' | 'error' => {
  switch (status) {
    case 'completed':  return 'success';
    case 'in_progress': return 'in-progress';
    case 'planned':    return 'pending';
    case 'cancelled':  return 'error';
  }
};

const TransitionsPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const { getPageSize, setPageSize, getVisibleColumns, setVisibleColumns } = usePreferences();
  const [allTransitions, setAllTransitions] = useState<Transition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const pageSize = getPageSize('transitions');
  const visibleContent = getVisibleColumns('transitions') ?? DEFAULT_VISIBLE;

  const fetchTransitions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await transitionsApi.list({ page_size: 1000 });
      setAllTransitions(res.data.items);
    } catch {
      setError('Failed to load transitions.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTransitions();
  }, [fetchTransitions]);

  const { items, filteredItemsCount, collectionProps, paginationProps, propertyFilterProps } =
    useCollection(allTransitions, {
      propertyFiltering: {
        filteringProperties: [
          {
            key: 'transition_type',
            operators: ['='],
            propertyLabel: 'Type',
            groupValuesLabel: 'Types',
          },
          {
            key: 'status',
            operators: ['='],
            propertyLabel: 'Status',
            groupValuesLabel: 'Statuses',
          },
        ],
        empty: (
          <Box textAlign="center" color="inherit">
            <b>No transitions</b>
            <Box padding={{ bottom: 's' }} variant="p" color="inherit">
              No transitions to display.
            </Box>
          </Box>
        ),
        noMatch: (
          <Box textAlign="center" color="inherit">
            <b>No matches</b>
            <Box padding={{ bottom: 's' }} variant="p" color="inherit">
              No transitions match the filter criteria.
            </Box>
          </Box>
        ),
      },
      pagination: { pageSize },
      sorting: {},
    });

  const columnDefinitions = [
    {
      id: 'office',
      header: 'Office',
      cell: (item: Transition) => item.office?.location_name ?? '—',
      sortingField: 'office_id',
    },
    {
      id: 'transition_type',
      header: 'Type',
      cell: (item: Transition) => capitalize(item.transition_type),
      sortingField: 'transition_type',
    },
    {
      id: 'status',
      header: 'Status',
      cell: (item: Transition) => (
        <StatusIndicator type={statusIndicatorType(item.status)}>
          {capitalize(item.status)}
        </StatusIndicator>
      ),
      sortingField: 'status',
    },
    {
      id: 'start_date',
      header: 'Start Date',
      cell: (item: Transition) => item.start_date ?? '—',
      sortingField: 'start_date',
    },
    {
      id: 'target_date',
      header: 'Target Date',
      cell: (item: Transition) => item.target_date ?? '—',
      sortingField: 'target_date',
    },
    {
      id: 'checklist',
      header: 'Checklist Progress',
      cell: (item: Transition) => {
        const total = item.checklist_items?.length ?? 0;
        const completed = item.checklist_items?.filter((c) => c.is_complete).length ?? 0;
        return total > 0 ? `${completed} / ${total}` : '—';
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
              <Button onClick={fetchTransitions} iconName="refresh" />
              {canEdit && <Button iconName="upload" onClick={() => setShowImport(true)}>Import</Button>}
              <Button
                iconName="download"
                onClick={async () => {
                  const res = await transitionsApi.exportCsv();
                  const url = window.URL.createObjectURL(new Blob([res.data]));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'transitions.csv';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export CSV
              </Button>
              {canEdit && (
                <Button variant="primary" onClick={() => navigate('/transitions/new')}>
                  Create Transition
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Transitions
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        <Table
          {...collectionProps}
          loading={loading}
          loadingText="Loading transitions..."
          columnDefinitions={columnDefinitions}
          visibleColumns={visibleContent}
          items={items}
          onRowClick={({ detail }) => navigate(`/transitions/${detail.item.id}`)}
          filter={
            <PropertyFilter
              {...propertyFilterProps}
              countText={`${filteredItemsCount} matches`}
              expandToViewport
            />
          }
          pagination={<Pagination {...paginationProps} />}
          preferences={
            <CollectionPreferences
              title="Preferences"
              confirmLabel="Confirm"
              cancelLabel="Cancel"
              preferences={{ pageSize, visibleContent }}
              onConfirm={({ detail }) => {
                if (detail.pageSize) setPageSize('transitions', detail.pageSize);
                if (detail.visibleContent) setVisibleColumns('transitions', detail.visibleContent as string[]);
              }}
              pageSizePreference={{
                title: 'Page size',
                options: [
                  { value: 10, label: '10 transitions' },
                  { value: 20, label: '20 transitions' },
                  { value: 50, label: '50 transitions' },
                ],
              }}
              visibleContentPreference={{
                title: 'Select visible content',
                options: [
                  {
                    label: 'Transition fields',
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
            <Header counter={loading ? undefined : `(${allTransitions.length})`}>
              Transitions
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <b>No transitions found.</b>
            </Box>
          }
        />
      </SpaceBetween>
      <ImportModal
        visible={showImport}
        onDismiss={() => setShowImport(false)}
        entityName="transitions"
        entityLabel="Transitions"
        onComplete={fetchTransitions}
      />
    </ContentLayout>
  );
};

export default TransitionsPage;
