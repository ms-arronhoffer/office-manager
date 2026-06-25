import React, { useCallback, useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Modal from '@cloudscape-design/components/modal';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Alert from '@cloudscape-design/components/alert';
import { ticketCategories as categoriesApi } from '@/api';
import type { TicketCategory } from '@/types';
import { useAuth } from '@/auth/AuthContext';

type ModalMode = 'create' | 'delete' | null;

const TicketCategoriesPage: React.FC = () => {
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const isAdmin = user?.role === 'admin';

  const [categories, setCategories] = useState<TicketCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [selectedCategory, setSelectedCategory] = useState<TicketCategory | null>(null);
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState('');

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchCategories = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await categoriesApi.list();
      setCategories(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError('Failed to load categories.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  const openCreateModal = () => {
    setSelectedCategory(null);
    setName('');
    setNameError('');
    setActionError(null);
    setModalMode('create');
  };

  const openDeleteModal = (cat: TicketCategory) => {
    setSelectedCategory(cat);
    setActionError(null);
    setModalMode('delete');
  };

  const closeModal = () => {
    setModalMode(null);
    setSelectedCategory(null);
    setActionError(null);
  };

  const handleCreate = async () => {
    if (!name.trim()) {
      setNameError('Name is required.');
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await categoriesApi.create({ name: name.trim() });
      closeModal();
      fetchCategories();
    } catch {
      setActionError('Failed to create category. It may already exist.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedCategory) return;
    setDeleting(true);
    setActionError(null);
    try {
      await categoriesApi.delete(selectedCategory.id);
      closeModal();
      fetchCategories();
    } catch {
      setActionError('Failed to delete category. It may have existing tickets.');
    } finally {
      setDeleting(false);
    }
  };

  const columnDefinitions = [
    {
      id: 'name',
      header: 'Category Name',
      cell: (item: TicketCategory) => item.name,
      sortingField: 'name',
    },
    {
      id: 'created_at',
      header: 'Created',
      cell: (item: TicketCategory) =>
        item.created_at ? new Date(item.created_at).toLocaleDateString() : '—',
    },
    ...(isAdmin
      ? [
          {
            id: 'actions',
            header: 'Actions',
            cell: (item: TicketCategory) => (
              <Button
                variant="inline-link"
                onClick={(e) => {
                  e.stopPropagation();
                  openDeleteModal(item);
                }}
              >
                Delete
              </Button>
            ),
          },
        ]
      : []),
  ];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button iconName="refresh" onClick={fetchCategories} />
              {canEdit && (
                <Button variant="primary" onClick={openCreateModal}>
                  Add Category
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Ticket Categories
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
          loading={loading}
          loadingText="Loading categories..."
          columnDefinitions={columnDefinitions}
          items={categories}
          sortingDisabled={false}
          header={
            <Header counter={loading ? undefined : `(${categories.length})`}>
              Categories
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No categories found</b>
                {canEdit && (
                  <Button onClick={openCreateModal}>Add category</Button>
                )}
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>

      {/* Create Modal */}
      <Modal
        visible={modalMode === 'create'}
        onDismiss={closeModal}
        header="Add Category"
        size="medium"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={closeModal} disabled={saving}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleCreate} loading={saving} loadingText="Saving...">
                Add Category
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Form>
          <SpaceBetween size="m">
            {actionError && (
              <Alert type="error" dismissible onDismiss={() => setActionError(null)}>
                {actionError}
              </Alert>
            )}
            <FormField label="Category Name" errorText={nameError}>
              <Input
                value={name}
                onChange={({ detail }) => {
                  setName(detail.value);
                  setNameError('');
                }}
                placeholder="e.g. Plumbing, Electrical, HVAC"
                disabled={saving}
              />
            </FormField>
          </SpaceBetween>
        </Form>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        visible={modalMode === 'delete'}
        onDismiss={closeModal}
        header="Delete Category"
        size="small"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={closeModal} disabled={deleting}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleDelete} loading={deleting} loadingText="Deleting...">
                Delete
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {actionError && (
            <Alert type="error" dismissible onDismiss={() => setActionError(null)}>
              {actionError}
            </Alert>
          )}
          <Box variant="p">
            Are you sure you want to delete the category{' '}
            <strong>{selectedCategory?.name}</strong>? Categories with existing tickets cannot be
            deleted.
          </Box>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default TicketCategoriesPage;
