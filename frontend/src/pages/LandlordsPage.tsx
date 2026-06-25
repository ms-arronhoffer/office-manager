import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCollection } from '@cloudscape-design/collection-hooks';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import TextFilter from '@cloudscape-design/components/text-filter';
import Pagination from '@cloudscape-design/components/pagination';
import CollectionPreferences from '@cloudscape-design/components/collection-preferences';
import Alert from '@cloudscape-design/components/alert';
import { landlords as landlordsApi } from '@/api';
import type { Landlord } from '@/types';
import { usePreferences } from '@/context/PreferencesContext';
import ImportModal from '@/components/common/ImportModal';
import { useAttachmentCounts } from '@/hooks/useAttachmentCounts';

const DEFAULT_VISIBLE = ['office_name', 'landlord_company', 'contact_name', 'contact_email', 'contact_phone', 'vendor_id', 'attachments'];

const LandlordsPage: React.FC = () => {
  const navigate = useNavigate();
  const { getPageSize, setPageSize, getVisibleColumns, setVisibleColumns } = usePreferences();
  const [allLandlords, setAllLandlords] = useState<Landlord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const pageSize = getPageSize('landlords');
  const visibleContent = getVisibleColumns('landlords') ?? DEFAULT_VISIBLE;

  const fetchLandlords = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await landlordsApi.list({ page_size: 1000 });
      setAllLandlords(res.data.items);
    } catch {
      setError('Failed to load landlords.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLandlords();
  }, [fetchLandlords]);

  const { items, filteredItemsCount, collectionProps, filterProps, paginationProps } =
    useCollection(allLandlords, {
      filtering: {
        empty: (
          <Box textAlign="center" color="inherit" padding="l">
            <b>No landlords</b>
          </Box>
        ),
        noMatch: (
          <Box textAlign="center" color="inherit" padding="l">
            <b>No matches</b>
          </Box>
        ),
        filteringFunction: (item: Landlord, filteringText: string) => {
          const text = filteringText.toLowerCase();
          return (
            (item.contact_name?.toLowerCase().includes(text) ?? false) ||
            (item.landlord_company?.toLowerCase().includes(text) ?? false) ||
            (item.office_name?.toLowerCase().includes(text) ?? false)
          );
        },
      },
      pagination: { pageSize },
      sorting: {},
    });

  const attachmentCounts = useAttachmentCounts(
    'landlord',
    items.map((l) => l.id),
  );

  const columnDefinitions = [
    { id: 'office_name', header: 'Office', cell: (item: Landlord) => item.office_name || '—', sortingField: 'office_name' },
    { id: 'landlord_company', header: 'Company', cell: (item: Landlord) => item.landlord_company || '—', sortingField: 'landlord_company' },
    { id: 'contact_name', header: 'Contact', cell: (item: Landlord) => item.contact_name || '—' },
    { id: 'contact_email', header: 'Email', cell: (item: Landlord) => item.contact_email || '—' },
    { id: 'contact_phone', header: 'Phone', cell: (item: Landlord) => item.contact_phone || '—' },
    { id: 'vendor_id', header: 'Vendor ID', cell: (item: Landlord) => item.vendor_id || '—' },
    {
      id: 'attachments',
      header: 'Attachments',
      cell: (item: Landlord) => attachmentCounts[item.id] ?? 0,
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
              <Button onClick={fetchLandlords} iconName="refresh" />
              <Button iconName="upload" onClick={() => setShowImport(true)}>Import</Button>
              <Button
                iconName="download"
                onClick={async () => {
                  const res = await landlordsApi.exportCsv();
                  const url = window.URL.createObjectURL(new Blob([res.data]));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'landlords.csv';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export CSV
              </Button>
              <Button variant="primary" onClick={() => navigate('/landlords/new')}>
                Create Landlord
              </Button>
            </SpaceBetween>
          }
        >
          Landlords
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
          loadingText="Loading landlords..."
          columnDefinitions={columnDefinitions}
          visibleColumns={visibleContent}
          items={items}
          onRowClick={({ detail }) => navigate(`/landlords/${detail.item.id}`)}
          filter={
            <TextFilter
              {...filterProps}
              filteringPlaceholder="Find by name, company, or office"
              countText={filteredItemsCount !== undefined ? `${filteredItemsCount} matches` : undefined}
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
                if (detail.pageSize) setPageSize('landlords', detail.pageSize);
                if (detail.visibleContent) setVisibleColumns('landlords', detail.visibleContent as string[]);
              }}
              pageSizePreference={{
                title: 'Page size',
                options: [
                  { value: 10, label: '10 landlords' },
                  { value: 20, label: '20 landlords' },
                  { value: 50, label: '50 landlords' },
                ],
              }}
              visibleContentPreference={{
                title: 'Select visible content',
                options: [
                  {
                    label: 'Landlord fields',
                    options: columnDefinitions.map((col) => ({
                      id: col.id,
                      label: col.header as string,
                    })),
                  },
                ],
              }}
            />
          }
          header={<Header counter={loading ? undefined : `(${allLandlords.length})`}>Landlords</Header>}
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No landlords</b>
                <Button onClick={() => navigate('/landlords/new')}>Create landlord</Button>
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>
      <ImportModal
        visible={showImport}
        onDismiss={() => setShowImport(false)}
        entityName="landlords"
        entityLabel="Landlords"
        onComplete={fetchLandlords}
      />
    </ContentLayout>
  );
};

export default LandlordsPage;
