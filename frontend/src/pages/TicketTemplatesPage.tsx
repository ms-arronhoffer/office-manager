import React, { useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Multiselect from '@cloudscape-design/components/multiselect';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import {
  ticketTemplates as templatesApi,
  ticketCategories as categoriesApi,
  offices as officesApi,
  managers as managersApi,
} from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import ConfirmDeleteModal from '@/components/common/ConfirmDeleteModal';
import type { TicketTemplate, TicketCategory, Office, Manager } from '@/types';

const PRIORITIES = [
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
];

interface FormState {
  name: string;
  subject: string;
  description: string;
  priority: string;
  category_id: string;
  office_id: string;
  assigned_to_id: string;
}

const EMPTY: FormState = {
  name: '',
  subject: '',
  description: '',
  priority: 'low',
  category_id: '',
  office_id: '',
  assigned_to_id: '',
};

const TicketTemplatesPage: React.FC = () => {
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [templates, setTemplates] = useState<TicketTemplate[]>([]);
  const [categories, setCategories] = useState<TicketCategory[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [managers, setManagers] = useState<Manager[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<TicketTemplate | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<TicketTemplate | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [bulkTarget, setBulkTarget] = useState<TicketTemplate | null>(null);
  const [bulkOffices, setBulkOffices] = useState<{ label: string; value: string }[]>([]);
  const [bulkSaving, setBulkSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [tRes, cRes, oRes, mRes] = await Promise.all([
        templatesApi.list(),
        categoriesApi.list(),
        officesApi.list({ page_size: 1000 }),
        managersApi.list(),
      ]);
      setTemplates(tRes.data);
      setCategories(cRes.data);
      setOffices(oRes.data.items);
      setManagers(mRes.data);
    } catch {
      setError('Failed to load templates.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY);
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (t: TicketTemplate) => {
    setEditing(t);
    setForm({
      name: t.name,
      subject: t.subject,
      description: t.description || '',
      priority: t.priority,
      category_id: t.category_id || '',
      office_id: t.office_id || '',
      assigned_to_id: t.assigned_to_id || '',
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim() || !form.subject.trim()) {
      setFormError('Name and Subject are required.');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        name: form.name,
        subject: form.subject,
        description: form.description || undefined,
        priority: form.priority,
        category_id: form.category_id || undefined,
        office_id: form.office_id || undefined,
        assigned_to_id: form.assigned_to_id || undefined,
      };
      if (editing) {
        await templatesApi.update(editing.id, payload);
        addFlash({ type: 'success', content: 'Template updated.' });
      } else {
        await templatesApi.create(payload);
        addFlash({ type: 'success', content: 'Template created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      setFormError('Failed to save template.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await templatesApi.delete(deleteTarget.id);
      addFlash({ type: 'success', content: `Deleted template "${deleteTarget.name}".` });
      setDeleteTarget(null);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete template.' });
    } finally {
      setDeleting(false);
    }
  };

  const handleBulkCreate = async () => {
    if (!bulkTarget || bulkOffices.length === 0) return;
    setBulkSaving(true);
    try {
      const res = await templatesApi.bulkCreate(bulkTarget.id, bulkOffices.map((o) => o.value));
      addFlash({ type: 'success', content: `Created ${res.data.created} ticket(s) from template "${bulkTarget.name}".` });
      setBulkTarget(null);
      setBulkOffices([]);
    } catch {
      addFlash({ type: 'error', content: 'Failed to create tickets from template.' });
    } finally {
      setBulkSaving(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  const categoryOptions = [
    { label: '— None —', value: '' },
    ...categories.map((c) => ({ label: c.name, value: c.id })),
  ];
  const officeOptions = [
    { label: '— None —', value: '' },
    ...offices.map((o) => ({ label: o.location_name, value: o.id })),
  ];
  const managerOptions = [
    { label: '— None —', value: '' },
    ...managers.map((m) => ({ label: m.name, value: m.id })),
  ];

  return (
    <>
      <ConfirmDeleteModal
        visible={!!deleteTarget}
        itemName={deleteTarget?.name ?? ''}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        loading={deleting}
      />

      {/* Bulk-create tickets from template */}
      <Modal
        visible={!!bulkTarget}
        onDismiss={() => { setBulkTarget(null); setBulkOffices([]); }}
        header={`Create tickets from: ${bulkTarget?.name ?? ''}`}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => { setBulkTarget(null); setBulkOffices([]); }}>Cancel</Button>
              <Button
                variant="primary"
                loading={bulkSaving}
                disabled={bulkOffices.length === 0}
                onClick={handleBulkCreate}
              >
                Create {bulkOffices.length > 0 ? `${bulkOffices.length} ` : ''}Ticket{bulkOffices.length !== 1 ? 's' : ''}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <FormField label="Select offices" description="A ticket will be created for each selected office.">
          <Multiselect
            selectedOptions={bulkOffices}
            options={offices.map((o) => ({ label: o.location_name, value: o.id }))}
            onChange={({ detail }) => setBulkOffices(detail.selectedOptions.map((o) => ({ label: o.label ?? '', value: o.value ?? '' })))}
            placeholder="Choose offices..."
            filteringType="auto"
          />
        </FormField>
      </Modal>

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editing ? 'Edit Template' : 'Create Template'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={saving} onClick={handleSave}>
                {editing ? 'Save Changes' : 'Create'}
              </Button>
            </SpaceBetween>
          </Box>
        }
        size="medium"
      >
        <SpaceBetween size="m">
          {formError && <Alert type="error">{formError}</Alert>}
          <FormField label="Template Name" constraintText="Required">
            <Input value={form.name} onChange={({ detail }) => setForm((f) => ({ ...f, name: detail.value }))} />
          </FormField>
          <FormField label="Subject" constraintText="Required">
            <Input value={form.subject} onChange={({ detail }) => setForm((f) => ({ ...f, subject: detail.value }))} />
          </FormField>
          <FormField label="Description">
            <Textarea value={form.description} onChange={({ detail }) => setForm((f) => ({ ...f, description: detail.value }))} rows={4} />
          </FormField>
          <FormField label="Priority">
            <Select
              selectedOption={PRIORITIES.find((p) => p.value === form.priority) ?? null}
              options={PRIORITIES}
              onChange={({ detail }) => setForm((f) => ({ ...f, priority: detail.selectedOption.value ?? 'low' }))}
            />
          </FormField>
          <FormField label="Category">
            <Select
              selectedOption={categoryOptions.find((o) => o.value === form.category_id) ?? null}
              options={categoryOptions}
              onChange={({ detail }) => setForm((f) => ({ ...f, category_id: detail.selectedOption.value ?? '' }))}
            />
          </FormField>
          <FormField label="Office">
            <Select
              selectedOption={officeOptions.find((o) => o.value === form.office_id) ?? null}
              options={officeOptions}
              onChange={({ detail }) => setForm((f) => ({ ...f, office_id: detail.selectedOption.value ?? '' }))}
            />
          </FormField>
          <FormField label="Assigned To">
            <Select
              selectedOption={managerOptions.find((o) => o.value === form.assigned_to_id) ?? null}
              options={managerOptions}
              onChange={({ detail }) => setForm((f) => ({ ...f, assigned_to_id: detail.selectedOption.value ?? '' }))}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      <ContentLayout
        header={
          <Header
            variant="h1"
            actions={
              canEdit && (
                <Button variant="primary" onClick={openCreate}>Create Template</Button>
              )
            }
          >
            Ticket Templates
          </Header>
        }
      >
        <Container>
          {error && <Alert type="error">{error}</Alert>}
          <Table
            columnDefinitions={[
              { id: 'name', header: 'Name', cell: (t: TicketTemplate) => t.name },
              { id: 'subject', header: 'Subject', cell: (t: TicketTemplate) => t.subject },
              {
                id: 'priority',
                header: 'Priority',
                cell: (t: TicketTemplate) => (
                  <Badge color={t.priority === 'high' ? 'red' : t.priority === 'medium' ? 'blue' : 'grey'}>
                    {t.priority.charAt(0).toUpperCase() + t.priority.slice(1)}
                  </Badge>
                ),
              },
              { id: 'category', header: 'Category', cell: (t: TicketTemplate) => t.category?.name ?? '—' },
              { id: 'office', header: 'Office', cell: (t: TicketTemplate) => t.office?.location_name ?? '—' },
              ...(canEdit
                ? [{
                    id: 'actions',
                    header: '',
                    cell: (t: TicketTemplate) => (
                      <SpaceBetween direction="horizontal" size="xs">
                        <Button variant="inline-icon" iconName="add-plus" ariaLabel="Create Tickets" title="Create tickets from template" onClick={() => { setBulkTarget(t); setBulkOffices([]); }} />
                        <Button variant="inline-icon" iconName="edit" ariaLabel="Edit" onClick={() => openEdit(t)} />
                        <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => setDeleteTarget(t)} />
                      </SpaceBetween>
                    ),
                  }]
                : []),
            ]}
            items={templates}
            empty={
              <Box textAlign="center" color="inherit" padding="m">
                No templates yet.{canEdit && ' Click "Create Template" to get started.'}
              </Box>
            }
          />
        </Container>
      </ContentLayout>
    </>
  );
};

export default TicketTemplatesPage;
