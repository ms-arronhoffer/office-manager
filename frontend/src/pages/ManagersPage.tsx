import React, { useCallback, useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Modal from '@cloudscape-design/components/modal';
import EntityFormModal from '@/components/common/EntityFormModal';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Alert from '@cloudscape-design/components/alert';
import { managers as managersApi } from '@/api';
import type { Manager } from '@/types';
import { useAuth } from '@/auth/AuthContext';
import ImportModal from '@/components/common/ImportModal';

type ModalMode = 'create' | 'edit' | 'delete' | null;

interface ManagerFormState {
  name: string;
  email: string;
  phone: string;
}

const emptyForm = (): ManagerFormState => ({
  name: '',
  email: '',
  phone: '',
});

const formFromManager = (m: Manager): ManagerFormState => ({
  name: m.name,
  email: m.email ?? '',
  phone: m.phone ?? '',
});

const ManagersPage: React.FC = () => {
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const isAdmin = user?.role === 'admin';

  const [managerList, setManagerList] = useState<Manager[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);

  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [selectedManager, setSelectedManager] = useState<Manager | null>(null);
  const [form, setForm] = useState<ManagerFormState>(emptyForm());
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof ManagerFormState, string>>>({});

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchManagers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await managersApi.list();
      setManagerList(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError('Failed to load managers.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchManagers();
  }, [fetchManagers]);

  const openCreateModal = () => {
    setSelectedManager(null);
    setForm(emptyForm());
    setFormErrors({});
    setActionError(null);
    setModalMode('create');
  };

  const openEditModal = (m: Manager) => {
    setSelectedManager(m);
    setForm(formFromManager(m));
    setFormErrors({});
    setActionError(null);
    setModalMode('edit');
  };

  const openDeleteModal = (m: Manager) => {
    setSelectedManager(m);
    setActionError(null);
    setModalMode('delete');
  };

  const closeModal = () => {
    setModalMode(null);
    setSelectedManager(null);
    setActionError(null);
  };

  const validate = (): boolean => {
    const errors: Partial<Record<keyof ManagerFormState, string>> = {};
    if (!form.name.trim()) errors.name = 'Name is required.';
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    setActionError(null);
    try {
      const payload = {
        name: form.name.trim(),
        email: form.email.trim() || undefined,
        phone: form.phone.trim() || undefined,
      };
      if (modalMode === 'create') {
        await managersApi.create(payload);
      } else if (modalMode === 'edit' && selectedManager) {
        await managersApi.update(selectedManager.id, payload);
      }
      closeModal();
      fetchManagers();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail;
      setActionError(
        detail ||
          (modalMode === 'create'
            ? 'Failed to create manager.'
            : 'Failed to update manager.'),
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedManager) return;
    setDeleting(true);
    setActionError(null);
    try {
      await managersApi.delete(selectedManager.id);
      closeModal();
      fetchManagers();
    } catch {
      setActionError('Failed to delete manager. They may be assigned to offices.');
    } finally {
      setDeleting(false);
    }
  };

  const columnDefinitions = [
    {
      id: 'name',
      header: 'Name',
      cell: (item: Manager) => item.name,
      sortingField: 'name',
    },
    {
      id: 'email',
      header: 'Email',
      cell: (item: Manager) => item.email ?? '—',
    },
    {
      id: 'phone',
      header: 'Phone',
      cell: (item: Manager) => item.phone ?? '—',
    },
    ...(canEdit
      ? [
          {
            id: 'actions',
            header: 'Actions',
            cell: (item: Manager) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  variant="inline-link"
                  onClick={(e) => {
                    e.stopPropagation();
                    openEditModal(item);
                  }}
                >
                  Edit
                </Button>
                {isAdmin && (
                  <Button
                    variant="inline-link"
                    onClick={(e) => {
                      e.stopPropagation();
                      openDeleteModal(item);
                    }}
                  >
                    Delete
                  </Button>
                )}
              </SpaceBetween>
            ),
          },
        ]
      : []),
  ];

  const isCreateOrEdit = modalMode === 'create' || modalMode === 'edit';
  const modalTitle = modalMode === 'create' ? 'Add Manager' : 'Edit Manager';

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button iconName="refresh" onClick={fetchManagers} />
              {canEdit && <Button iconName="upload" onClick={() => setShowImport(true)}>Import</Button>}
              {canEdit && (
                <Button variant="primary" onClick={openCreateModal}>
                  Add Manager
                </Button>
              )}
            </SpaceBetween>
          }
        >
          Managers
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
          loadingText="Loading managers..."
          columnDefinitions={columnDefinitions}
          items={managerList}
          sortingDisabled={false}
          header={
            <Header counter={loading ? undefined : `(${managerList.length})`}>Managers</Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No managers found</b>
                {canEdit && (
                  <Button onClick={openCreateModal}>Add manager</Button>
                )}
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>

      {/* Create / Edit Modal */}
      <EntityFormModal
        visible={isCreateOrEdit}
        title={modalTitle}
        onCancel={closeModal}
        onSubmit={handleSave}
        submitting={saving}
        submitLabel={modalMode === 'create' ? 'Add Manager' : 'Save Changes'}
        size="medium"
      >
        <Form>
          <SpaceBetween size="m">
            {actionError && (
              <Alert type="error" dismissible onDismiss={() => setActionError(null)}>
                {actionError}
              </Alert>
            )}

            <FormField label="Name" errorText={formErrors.name}>
              <Input
                value={form.name}
                onChange={({ detail }) => setForm((prev) => ({ ...prev, name: detail.value }))}
                placeholder="Manager name"
                disabled={saving}
              />
            </FormField>

            <FormField label="Email">
              <Input
                type="email"
                value={form.email}
                onChange={({ detail }) => setForm((prev) => ({ ...prev, email: detail.value }))}
                placeholder="manager@example.com"
                disabled={saving}
              />
            </FormField>

            <FormField label="Phone">
              <Input
                value={form.phone}
                onChange={({ detail }) => setForm((prev) => ({ ...prev, phone: detail.value }))}
                placeholder="(555) 123-4567"
                disabled={saving}
              />
            </FormField>
          </SpaceBetween>
        </Form>
      </EntityFormModal>

      {/* Delete Confirmation Modal */}
      <Modal
        visible={modalMode === 'delete'}
        onDismiss={closeModal}
        header="Delete Manager"
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
            Are you sure you want to delete <strong>{selectedManager?.name}</strong>? This manager
            will be removed from any offices they are assigned to.
          </Box>
        </SpaceBetween>
      </Modal>
      <ImportModal
        visible={showImport}
        onDismiss={() => setShowImport(false)}
        entityName="managers"
        entityLabel="Managers"
        onComplete={fetchManagers}
      />
    </ContentLayout>
  );
};

export default ManagersPage;
