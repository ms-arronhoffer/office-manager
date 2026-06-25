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
import Alert from '@cloudscape-design/components/alert';
import Link from '@cloudscape-design/components/link';
import { managementCompanies as api } from '@/api';
import type { ManagementCompany } from '@/types';
import { useAuth } from '@/auth/AuthContext';

const ManagementCompaniesPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const [allItems, setAllItems] = useState<ManagementCompany[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.list({ page_size: 1000 });
      setAllItems(res.data.items);
    } catch {
      setError('Failed to load management companies.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  const { items, filteredItemsCount, collectionProps, filterProps, paginationProps } = useCollection(
    allItems,
    {
      filtering: {
        empty: (
          <Box textAlign="center" color="inherit" padding="l">
            <b>No management companies</b>
          </Box>
        ),
        noMatch: (
          <Box textAlign="center" color="inherit" padding="l">
            <b>No matches</b>
          </Box>
        ),
        filteringFunction: (item: ManagementCompany, filteringText: string) => {
          const text = filteringText.toLowerCase();
          return (
            (item.name?.toLowerCase().includes(text) ?? false) ||
            (item.contact_name?.toLowerCase().includes(text) ?? false) ||
            (item.contact_email?.toLowerCase().includes(text) ?? false)
          );
        },
      },
      pagination: { pageSize: 20 },
      sorting: {},
    },
  );

  const columnDefinitions = [
    {
      id: 'name',
      header: 'Company',
      cell: (item: ManagementCompany) => (
        <Link onFollow={() => navigate(`/management-companies/${item.id}`)}>{item.name}</Link>
      ),
      sortingField: 'name',
    },
    { id: 'contact_name', header: 'Contact', cell: (item: ManagementCompany) => item.contact_name || '—' },
    { id: 'contact_email', header: 'Email', cell: (item: ManagementCompany) => item.contact_email || '—' },
    { id: 'contact_phone', header: 'Phone', cell: (item: ManagementCompany) => item.contact_phone || '—' },
    {
      id: 'website',
      header: 'Website',
      cell: (item: ManagementCompany) =>
        item.website ? (
          <Link external href={item.website}>
            {item.website}
          </Link>
        ) : (
          '—'
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
              <Button onClick={fetchItems} iconName="refresh" />
              {canEdit && (
                <Button variant="primary" onClick={() => navigate('/management-companies/new')}>
                  Create Management Company
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Property Management Companies
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
          loadingText="Loading management companies..."
          columnDefinitions={columnDefinitions}
          items={items}
          onRowClick={({ detail }) => navigate(`/management-companies/${detail.item.id}`)}
          filter={
            <TextFilter
              {...filterProps}
              filteringPlaceholder="Find by company, contact, or email"
              countText={filteredItemsCount !== undefined ? `${filteredItemsCount} matches` : undefined}
            />
          }
          pagination={<Pagination {...paginationProps} />}
          header={<Header counter={loading ? undefined : `(${allItems.length})`}>Management Companies</Header>}
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No management companies</b>
                {canEdit && (
                  <Button onClick={() => navigate('/management-companies/new')}>
                    Create management company
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

export default ManagementCompaniesPage;
