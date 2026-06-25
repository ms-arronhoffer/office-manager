import React, { useEffect, useState, useCallback } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Checkbox from '@cloudscape-design/components/checkbox';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { contacts as contactsApi } from '@/api';
import type { EntityContact, EntityContactType } from '@/types';

interface ContactsPanelProps {
  /** The entity these contacts belong to (landlord, vendor, management_company, ...). */
  entityType: EntityContactType;
  entityId: string;
  canEdit: boolean;
  /** Optional override for the section title. */
  title?: string;
}

const CONTACT_TYPE_OPTIONS = [
  { label: 'General', value: 'general' },
  { label: 'Billing', value: 'billing' },
  { label: 'Accounting', value: 'accounting' },
  { label: 'Maintenance', value: 'maintenance' },
  { label: 'Property Manager', value: 'property_manager' },
  { label: 'Leasing', value: 'leasing' },
  { label: 'Legal', value: 'legal' },
  { label: 'Emergency', value: 'emergency' },
];

const emptyForm = {
  contact_name: '',
  title: '',
  contact_type: '',
  department: '',
  is_primary: false,
  email: '',
  phone: '',
  mobile: '',
  notes: '',
};

function prettyType(value?: string): string {
  if (!value) return '—';
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const ContactsPanel: React.FC<ContactsPanelProps> = ({ entityType, entityId, canEdit, title }) => {
  const [items, setItems] = useState<EntityContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formVisible, setFormVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const hasValidEntity = Boolean(entityType && entityId);

  const fetchContacts = useCallback(async () => {
    if (!hasValidEntity) {
      setLoading(false);
      return;
    }
    try {
      const res = await contactsApi.list(entityType, entityId);
      setItems(res.data);
    } catch {
      setError('Failed to load contacts.');
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId, hasValidEntity]);

  useEffect(() => {
    fetchContacts();
  }, [fetchContacts]);

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...emptyForm });
    setFormVisible(true);
  };

  const openEdit = (c: EntityContact) => {
    setEditingId(c.id);
    setForm({
      contact_name: c.contact_name ?? '',
      title: c.title ?? '',
      contact_type: c.contact_type ?? '',
      department: c.department ?? '',
      is_primary: c.is_primary ?? false,
      email: c.email ?? '',
      phone: c.phone ?? '',
      mobile: c.mobile ?? '',
      notes: c.notes ?? '',
    });
    setFormVisible(true);
  };

  const closeForm = () => {
    setFormVisible(false);
    setEditingId(null);
    setForm({ ...emptyForm });
  };

  const handleSave = async () => {
    if (!form.contact_name.trim()) return;
    setSaving(true);
    setError(null);
    const payload = {
      contact_name: form.contact_name.trim(),
      title: form.title.trim() || undefined,
      contact_type: form.contact_type || undefined,
      department: form.department.trim() || undefined,
      is_primary: form.is_primary,
      email: form.email.trim() || undefined,
      phone: form.phone.trim() || undefined,
      mobile: form.mobile.trim() || undefined,
      notes: form.notes.trim() || undefined,
    };
    try {
      if (editingId) {
        await contactsApi.update(editingId, payload);
      } else {
        await contactsApi.create({ entity_type: entityType, entity_id: entityId, ...payload });
      }
      closeForm();
      await fetchContacts();
    } catch {
      setError(`Failed to ${editingId ? 'update' : 'add'} contact.`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    setDeletingId(id);
    setError(null);
    try {
      await contactsApi.delete(id);
      await fetchContacts();
    } catch {
      setError('Failed to delete contact.');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Container
      header={
        <Header
          variant="h2"
          counter={loading ? undefined : `(${items.length})`}
          actions={canEdit ? <Button onClick={openCreate}>Add Contact</Button> : undefined}
        >
          {title ?? 'Additional Contacts'}
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Table<EntityContact>
          loading={loading}
          loadingText="Loading contacts..."
          columnDefinitions={[
            { id: 'name', header: 'Name', cell: (item) => item.contact_name },
            { id: 'type', header: 'Type', cell: (item) => prettyType(item.contact_type) },
            {
              id: 'primary',
              header: 'Primary',
              cell: (item) =>
                item.is_primary ? (
                  <StatusIndicator type="success">Primary</StatusIndicator>
                ) : (
                  '—'
                ),
            },
            { id: 'title', header: 'Title', cell: (item) => item.title || '—' },
            { id: 'department', header: 'Department', cell: (item) => item.department || '—' },
            { id: 'email', header: 'Email', cell: (item) => item.email || '—' },
            { id: 'phone', header: 'Phone', cell: (item) => item.phone || '—' },
            { id: 'mobile', header: 'Mobile', cell: (item) => item.mobile || '—' },
            { id: 'notes', header: 'Notes', cell: (item) => item.notes || '—' },
            ...(canEdit
              ? [
                  {
                    id: 'actions',
                    header: '',
                    cell: (item: EntityContact) => (
                      <SpaceBetween direction="horizontal" size="xs">
                        <Button
                          variant="inline-icon"
                          iconName="edit"
                          ariaLabel="Edit contact"
                          onClick={() => openEdit(item)}
                        />
                        <Button
                          variant="inline-icon"
                          iconName="remove"
                          ariaLabel="Delete contact"
                          loading={deletingId === item.id}
                          onClick={() => handleDelete(item.id)}
                        />
                      </SpaceBetween>
                    ),
                    width: 100,
                  },
                ]
              : []),
          ]}
          items={items}
          empty={
            <Box textAlign="center" color="inherit" padding="m">
              No additional contacts.
            </Box>
          }
        />

        {formVisible && (
          <Container header={<Header variant="h3">{editingId ? 'Edit Contact' : 'New Contact'}</Header>}>
            <SpaceBetween size="s">
              <FormField label="Name" constraintText="Required">
                <Input
                  value={form.contact_name}
                  onChange={({ detail }) => setForm((f) => ({ ...f, contact_name: detail.value }))}
                  placeholder="Contact name"
                />
              </FormField>
              <FormField label="Title">
                <Input
                  value={form.title}
                  onChange={({ detail }) => setForm((f) => ({ ...f, title: detail.value }))}
                  placeholder="e.g., Property Manager"
                />
              </FormField>
              <FormField label="Contact Type" description="Helps route who to contact for what.">
                <Select
                  selectedOption={
                    form.contact_type
                      ? CONTACT_TYPE_OPTIONS.find((o) => o.value === form.contact_type) ?? null
                      : null
                  }
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, contact_type: detail.selectedOption.value ?? '' }))
                  }
                  options={CONTACT_TYPE_OPTIONS}
                  placeholder="Select a type"
                />
              </FormField>
              <FormField label="Department">
                <Input
                  value={form.department}
                  onChange={({ detail }) => setForm((f) => ({ ...f, department: detail.value }))}
                  placeholder="e.g., Accounts Receivable"
                />
              </FormField>
              <Checkbox
                checked={form.is_primary}
                onChange={({ detail }) => setForm((f) => ({ ...f, is_primary: detail.checked }))}
              >
                Primary contact
              </Checkbox>
              <FormField label="Email">
                <Input
                  value={form.email}
                  onChange={({ detail }) => setForm((f) => ({ ...f, email: detail.value }))}
                  placeholder="Email address"
                  type="email"
                />
              </FormField>
              <FormField label="Phone">
                <Input
                  value={form.phone}
                  onChange={({ detail }) => setForm((f) => ({ ...f, phone: detail.value }))}
                  placeholder="Phone number"
                />
              </FormField>
              <FormField label="Mobile">
                <Input
                  value={form.mobile}
                  onChange={({ detail }) => setForm((f) => ({ ...f, mobile: detail.value }))}
                  placeholder="Mobile number"
                />
              </FormField>
              <FormField label="Notes">
                <Input
                  value={form.notes}
                  onChange={({ detail }) => setForm((f) => ({ ...f, notes: detail.value }))}
                  placeholder="Additional info"
                />
              </FormField>
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={closeForm}>Cancel</Button>
                <Button
                  variant="primary"
                  onClick={handleSave}
                  loading={saving}
                  disabled={!form.contact_name.trim()}
                >
                  {editingId ? 'Save Changes' : 'Add Contact'}
                </Button>
              </SpaceBetween>
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>
    </Container>
  );
};

export default ContactsPanel;
