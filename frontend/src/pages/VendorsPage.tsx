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
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Alert from '@cloudscape-design/components/alert';
import { vendors as vendorsApi } from '@/api';
import type { Vendor } from '@/types';
import { usePreferences } from '@/context/PreferencesContext';
import { useAuth } from '@/auth/AuthContext';
import ImportModal from '@/components/common/ImportModal';
import { useAttachmentCounts } from '@/hooks/useAttachmentCounts';

const DEFAULT_VISIBLE = ['company_name', 'services', 'contact_name', 'contact_email', 'contact_phone', 'is_preferred', 'offices', 'attachments'];

const VendorsPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const { getPageSize, setPageSize, getVisibleColumns, setVisibleColumns } = usePreferences();
  const [allVendors, setAllVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const pageSize = getPageSize('vendors');
  const visibleContent = getVisibleColumns('vendors') ?? DEFAULT_VISIBLE;

  const fetchVendors = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await vendorsApi.list({ page_size: 1000 });
      setAllVendors(res.data.items);
    } catch {
      setError('Failed to load vendors.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchVendors();
  }, [fetchVendors]);

  const { items, filteredItemsCount, collectionProps, filterProps, paginationProps } =
    useCollection(allVendors, {
      filtering: {
        empty: (
          <Box textAlign="center" color="inherit" padding="l">
            <b>No vendors</b>
          </Box>
        ),
        noMatch: (
          <Box textAlign="center" color="inherit" padding="l">
            <b>No matches</b>
          </Box>
        ),
        filteringFunction: (item: Vendor, filteringText: string) => {
          const text = filteringText.toLowerCase();
          return (
            (item.company_name?.toLowerCase().includes(text) ?? false) ||
            (item.contact_name?.toLowerCase().includes(text) ?? false) ||
            (item.services?.toLowerCase().includes(text) ?? false)
          );
        },
      },
      pagination: { pageSize },
      sorting: {},
    });

  const attachmentCounts = useAttachmentCounts(
    'vendor',
    items.map((v) => v.id),
  );

  const columnDefinitions = [
    { id: 'company_name', header: 'Company', cell: (item: Vendor) => item.company_name || '—', sortingField: 'company_name' },
    { id: 'services', header: 'Services', cell: (item: Vendor) => item.services || '—' },
    { id: 'contact_name', header: 'Contact', cell: (item: Vendor) => item.contact_name || '—' },
    { id: 'contact_email', header: 'Email', cell: (item: Vendor) => item.contact_email || '—' },
    { id: 'contact_phone', header: 'Phone', cell: (item: Vendor) => item.contact_phone || '—' },
    {
      id: 'is_preferred',
      header: 'Preferred',
      cell: (item: Vendor) => (
        <StatusIndicator type={item.is_preferred ? 'success' : 'stopped'}>
          {item.is_preferred ? 'Yes' : 'No'}
        </StatusIndicator>
      ),
    },
    {
      id: 'offices',
      header: 'Offices',
      cell: (item: Vendor) =>
        item.offices?.length ? item.offices.map((o) => o.location_name).join(', ') : '—',
    },
    {
      id: 'attachments',
      header: 'Attachments',
      cell: (item: Vendor) => attachmentCounts[item.id] ?? 0,
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
              <Button onClick={fetchVendors} iconName="refresh" />
              {canEdit && <Button iconName="upload" onClick={() => setShowImport(true)}>Import</Button>}
              <Button
                iconName="download"
                onClick={async () => {
                  const res = await vendorsApi.exportCsv();
                  const url = window.URL.createObjectURL(new Blob([res.data]));
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'vendors.csv';
                  a.click();
                  window.URL.revokeObjectURL(url);
                }}
              >
                Export CSV
              </Button>
              {canEdit && (
                <Button variant="primary" onClick={() => navigate('/vendors/new')}>
                  Create Vendor
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Vendors
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
          loadingText="Loading vendors..."
          columnDefinitions={columnDefinitions}
          visibleColumns={visibleContent}
          items={items}
          onRowClick={({ detail }) => navigate(`/vendors/${detail.item.id}`)}
          filter={
            <TextFilter
              {...filterProps}
              filteringPlaceholder="Find by company, contact, or services"
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
                if (detail.pageSize) setPageSize('vendors', detail.pageSize);
                if (detail.visibleContent) setVisibleColumns('vendors', detail.visibleContent as string[]);
              }}
              pageSizePreference={{
                title: 'Page size',
                options: [
                  { value: 10, label: '10 vendors' },
                  { value: 20, label: '20 vendors' },
                  { value: 50, label: '50 vendors' },
                ],
              }}
              visibleContentPreference={{
                title: 'Select visible content',
                options: [
                  {
                    label: 'Vendor fields',
                    options: columnDefinitions.map((col) => ({
                      id: col.id,
                      label: col.header as string,
                    })),
                  },
                ],
              }}
            />
          }
          header={<Header counter={loading ? undefined : `(${allVendors.length})`}>Vendors</Header>}
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No vendors</b>
                {canEdit && <Button onClick={() => navigate('/vendors/new')}>Create vendor</Button>}
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>
      <ImportModal
        visible={showImport}
        onDismiss={() => setShowImport(false)}
        entityName="vendors"
        entityLabel="Vendors"
        onComplete={fetchVendors}
      />
    </ContentLayout>
  );
};

export default VendorsPage;
