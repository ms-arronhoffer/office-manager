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
import Select from '@cloudscape-design/components/select';
import Toggle from '@cloudscape-design/components/toggle';
import Badge from '@cloudscape-design/components/badge';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Alert from '@cloudscape-design/components/alert';
import { users as usersApi } from '@/api';
import type { User } from '@/types';
import { useAuth } from '@/auth/AuthContext';

type ModalMode = 'create' | 'edit' | 'delete' | null;

interface SelectOption {
  label: string;
  value: string;
}

const ROLE_OPTIONS: SelectOption[] = [
  { label: 'Admin', value: 'admin' },
  { label: 'Editor', value: 'editor' },
  { label: 'Accountant', value: 'accountant' },
  { label: 'Viewer', value: 'viewer' },
];

const roleBadgeColor = (role: User['role']): 'blue' | 'grey' | 'green' => {
  if (role === 'admin') return 'blue';
  if (role === 'editor') return 'green';
  return 'grey';
};

interface UserFormState {
  email: string;
  display_name: string;
  password: string;
  role: SelectOption | null;
  is_active: boolean;
}

const emptyForm = (): UserFormState => ({
  email: '',
  display_name: '',
  password: '',
  role: ROLE_OPTIONS.find((r) => r.value === 'viewer')!,
  is_active: true,
});

const formFromUser = (user: User): UserFormState => ({
  email: user.email,
  display_name: user.display_name,
  password: '',
  role: ROLE_OPTIONS.find((r) => r.value === user.role) ?? ROLE_OPTIONS.find((r) => r.value === 'viewer')!,
  is_active: user.is_active,
});

const UsersPage: React.FC = () => {
  const { user: currentUser } = useAuth();
  const isAdmin = currentUser?.role === 'admin';

  const [userList, setUserList] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [form, setForm] = useState<UserFormState>(emptyForm());
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof UserFormState, string>>>({});

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await usersApi.list();
      const data = res.data;
      setUserList(Array.isArray(data) ? data : (data as { items: User[] }).items ?? []);
    } catch {
      setError('Failed to load users. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  // ─── Modal helpers ────────────────────────────────────────────────────────────

  const openCreateModal = () => {
    setSelectedUser(null);
    setForm(emptyForm());
    setFormErrors({});
    setActionError(null);
    setModalMode('create');
  };

  const openEditModal = (user: User) => {
    setSelectedUser(user);
    setForm(formFromUser(user));
    setFormErrors({});
    setActionError(null);
    setModalMode('edit');
  };

  const openDeleteModal = (user: User) => {
    setSelectedUser(user);
    setActionError(null);
    setModalMode('delete');
  };

  const closeModal = () => {
    setModalMode(null);
    setSelectedUser(null);
    setActionError(null);
  };

  // ─── Validation ───────────────────────────────────────────────────────────────

  const validate = (): boolean => {
    const errors: Partial<Record<keyof UserFormState, string>> = {};
    if (!form.email.trim()) errors.email = 'Email is required.';
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
      errors.email = 'Enter a valid email address.';
    if (!form.display_name.trim()) errors.display_name = 'Full name is required.';
    if (modalMode === 'create' && !form.password)
      errors.password = 'Password is required when creating a user.';
    if (!form.role) errors.role = 'Role is required.';
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // ─── Save (create / edit) ─────────────────────────────────────────────────────

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    setActionError(null);
    try {
      if (modalMode === 'create') {
        await usersApi.create({
          email: form.email.trim(),
          display_name: form.display_name.trim(),
          password: form.password,
          role: form.role!.value as User['role'],
          is_active: form.is_active,
        });
      } else if (modalMode === 'edit' && selectedUser) {
        const payload: Partial<User> = {
          email: form.email.trim(),
          display_name: form.display_name.trim(),
          role: form.role!.value as User['role'],
          is_active: form.is_active,
        };
        await usersApi.update(selectedUser.id, payload);
      }
      closeModal();
      fetchUsers();
    } catch {
      setActionError(
        modalMode === 'create'
          ? 'Failed to create user. The email may already be in use.'
          : 'Failed to update user. Please try again.',
      );
    } finally {
      setSaving(false);
    }
  };

  // ─── Delete ───────────────────────────────────────────────────────────────────

  const handleDelete = async () => {
    if (!selectedUser) return;
    setDeleting(true);
    setActionError(null);
    try {
      await usersApi.delete(selectedUser.id);
      closeModal();
      fetchUsers();
    } catch {
      setActionError('Failed to delete user. Please try again.');
    } finally {
      setDeleting(false);
    }
  };

  // ─── Column definitions ───────────────────────────────────────────────────────

  const columnDefinitions = [
    {
      id: 'email',
      header: 'Email',
      cell: (item: User) => item.email,
      sortingField: 'email',
    },
    {
      id: 'display_name',
      header: 'Full Name',
      cell: (item: User) => item.display_name,
      sortingField: 'display_name',
    },
    {
      id: 'role',
      header: 'Role',
      cell: (item: User) => (
        <Badge color={roleBadgeColor(item.role)}>
          {item.role.charAt(0).toUpperCase() + item.role.slice(1)}
        </Badge>
      ),
    },
    {
      id: 'is_active',
      header: 'Status',
      cell: (item: User) =>
        item.is_active ? (
          <StatusIndicator type="success">Active</StatusIndicator>
        ) : (
          <StatusIndicator type="stopped">Inactive</StatusIndicator>
        ),
    },
    ...(isAdmin
      ? [
          {
            id: 'actions',
            header: 'Actions',
            cell: (item: User) => (
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
                <Button
                  variant="inline-link"
                  onClick={(e) => {
                    e.stopPropagation();
                    openDeleteModal(item);
                  }}
                  disabled={item.id === currentUser?.id}
                >
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]
      : []),
  ];

  // ─── Create / Edit modal ──────────────────────────────────────────────────────

  const isCreateOrEdit = modalMode === 'create' || modalMode === 'edit';
  const modalTitle = modalMode === 'create' ? 'Create User' : 'Edit User';

  // ─── Render ───────────────────────────────────────────────────────────────────

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          actions={
            isAdmin ? (
              <SpaceBetween direction="horizontal" size="xs">
                <Button iconName="refresh" onClick={fetchUsers} />
                <Button variant="primary" onClick={openCreateModal}>
                  Create User
                </Button>
              </SpaceBetween>
            ) : (
              <Button iconName="refresh" onClick={fetchUsers} />
            )
          }
        >
          Users
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        {!isAdmin && (
          <Alert type="info">
            You are viewing this page in read-only mode. Admin access is required to manage users.
          </Alert>
        )}

        <Table
          loading={loading}
          loadingText="Loading users..."
          columnDefinitions={columnDefinitions}
          items={userList}
          onRowClick={isAdmin ? ({ detail }) => openEditModal(detail.item) : undefined}
          sortingDisabled={false}
          header={
            <Header counter={loading ? undefined : `(${userList.length})`}>Users</Header>
          }
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <SpaceBetween size="m">
                <b>No users found</b>
                {isAdmin && (
                  <Button onClick={openCreateModal}>Create user</Button>
                )}
              </SpaceBetween>
            </Box>
          }
        />
      </SpaceBetween>

      {/* ── Create / Edit Modal ─────────────────────────────────────────────── */}
      <EntityFormModal
        visible={isCreateOrEdit}
        title={modalTitle}
        onCancel={closeModal}
        onSubmit={handleSave}
        submitting={saving}
        submitLabel={modalMode === 'create' ? 'Create User' : 'Save Changes'}
        size="medium"
      >
        <Form>
          <SpaceBetween size="m">
            {actionError && (
              <Alert type="error" dismissible onDismiss={() => setActionError(null)}>
                {actionError}
              </Alert>
            )}

            <FormField
              label="Email address"
              errorText={formErrors.email}
              constraintText="Must be a valid email address."
            >
              <Input
                type="email"
                value={form.email}
                onChange={({ detail }) =>
                  setForm((prev) => ({ ...prev, email: detail.value }))
                }
                placeholder="user@example.com"
                disabled={saving}
              />
            </FormField>

            <FormField label="Full name" errorText={formErrors.display_name}>
              <Input
                value={form.display_name}
                onChange={({ detail }) =>
                  setForm((prev) => ({ ...prev, display_name: detail.value }))
                }
                placeholder="Jane Smith"
                disabled={saving}
              />
            </FormField>

            {modalMode === 'create' && (
              <FormField
                label="Password"
                errorText={formErrors.password}
                constraintText="Minimum 8 characters recommended."
              >
                <Input
                  type="password"
                  value={form.password}
                  onChange={({ detail }) =>
                    setForm((prev) => ({ ...prev, password: detail.value }))
                  }
                  placeholder="Enter password"
                  disabled={saving}
                />
              </FormField>
            )}

            <FormField label="Role" errorText={formErrors.role}>
              <Select
                selectedOption={form.role}
                onChange={({ detail }) =>
                  setForm((prev) => ({
                    ...prev,
                    role: detail.selectedOption as SelectOption,
                  }))
                }
                options={ROLE_OPTIONS}
                placeholder="Select a role"
                disabled={saving}
              />
            </FormField>

            {modalMode === 'edit' && (
              <FormField label="Active">
                <Toggle
                  checked={form.is_active}
                  onChange={({ detail }) =>
                    setForm((prev) => ({ ...prev, is_active: detail.checked }))
                  }
                  disabled={saving || selectedUser?.id === currentUser?.id}
                >
                  {form.is_active ? 'Active' : 'Inactive'}
                </Toggle>
              </FormField>
            )}
          </SpaceBetween>
        </Form>
      </EntityFormModal>

      {/* ── Delete Confirmation Modal ───────────────────────────────────────── */}
      <Modal
        visible={modalMode === 'delete'}
        onDismiss={closeModal}
        header="Delete User"
        size="small"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={closeModal} disabled={deleting}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleDelete}
                loading={deleting}
                loadingText="Deleting..."
              >
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
            Are you sure you want to delete{' '}
            <strong>{selectedUser?.display_name ?? selectedUser?.email}</strong>? This action cannot
            be undone.
          </Box>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default UsersPage;
