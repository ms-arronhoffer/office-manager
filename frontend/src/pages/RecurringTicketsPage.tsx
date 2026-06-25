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
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Toggle from '@cloudscape-design/components/toggle';
import {
  recurringTicketRules as rulesApi,
  ticketCategories as categoriesApi,
  offices as officesApi,
  managers as managersApi,
} from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import ConfirmDeleteModal from '@/components/common/ConfirmDeleteModal';
import type { RecurringTicketRule, TicketCategory, Office, Manager } from '@/types';

const PRIORITIES = [
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
];

const FREQUENCIES = [
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
  { label: 'Monthly', value: 'monthly' },
];

const DAYS_OF_WEEK = [
  { label: 'Monday', value: '0' },
  { label: 'Tuesday', value: '1' },
  { label: 'Wednesday', value: '2' },
  { label: 'Thursday', value: '3' },
  { label: 'Friday', value: '4' },
  { label: 'Saturday', value: '5' },
  { label: 'Sunday', value: '6' },
];

interface FormState {
  name: string;
  subject: string;
  description: string;
  priority: string;
  category_id: string;
  office_id: string;
  assigned_to_id: string;
  frequency: string;
  day_of_week: string;
  day_of_month: string;
}

const EMPTY: FormState = {
  name: '',
  subject: '',
  description: '',
  priority: 'low',
  category_id: '',
  office_id: '',
  assigned_to_id: '',
  frequency: 'weekly',
  day_of_week: '0',
  day_of_month: '1',
};

function fmtDate(s?: string): string {
  if (!s) return '—';
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

const RecurringTicketsPage: React.FC = () => {
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [rules, setRules] = useState<RecurringTicketRule[]>([]);
  const [categories, setCategories] = useState<TicketCategory[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [managers, setManagers] = useState<Manager[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<RecurringTicketRule | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<RecurringTicketRule | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [rRes, cRes, oRes, mRes] = await Promise.all([
        rulesApi.list(),
        categoriesApi.list(),
        officesApi.list({ page_size: 1000 }),
        managersApi.list(),
      ]);
      setRules(rRes.data);
      setCategories(cRes.data);
      setOffices(oRes.data.items);
      setManagers(mRes.data);
    } catch {
      setError('Failed to load recurring ticket rules.');
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

  const openEdit = (r: RecurringTicketRule) => {
    setEditing(r);
    setForm({
      name: r.name,
      subject: r.subject,
      description: r.description || '',
      priority: r.priority,
      category_id: r.category_id || '',
      office_id: r.office_id || '',
      assigned_to_id: r.assigned_to_id || '',
      frequency: r.frequency,
      day_of_week: String(r.day_of_week ?? 0),
      day_of_month: String(r.day_of_month ?? 1),
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
        frequency: form.frequency,
        day_of_week: form.frequency === 'weekly' ? parseInt(form.day_of_week, 10) : undefined,
        day_of_month: form.frequency === 'monthly' ? parseInt(form.day_of_month, 10) : undefined,
      };
      if (editing) {
        await rulesApi.update(editing.id, payload);
        addFlash({ type: 'success', content: 'Rule updated.' });
      } else {
        await rulesApi.create(payload);
        addFlash({ type: 'success', content: 'Rule created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      setFormError('Failed to save rule.');
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (r: RecurringTicketRule) => {
    try {
      await rulesApi.toggle(r.id);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to toggle rule.' });
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await rulesApi.delete(deleteTarget.id);
      addFlash({ type: 'success', content: `Deleted rule "${deleteTarget.name}".` });
      setDeleteTarget(null);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete rule.' });
    } finally {
      setDeleting(false);
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

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editing ? 'Edit Recurring Rule' : 'Create Recurring Rule'}
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
          <FormField label="Rule Name" constraintText="Required">
            <Input value={form.name} onChange={({ detail }) => setForm((f) => ({ ...f, name: detail.value }))} />
          </FormField>
          <FormField label="Ticket Subject" constraintText="Required">
            <Input value={form.subject} onChange={({ detail }) => setForm((f) => ({ ...f, subject: detail.value }))} />
          </FormField>
          <FormField label="Description">
            <Textarea value={form.description} onChange={({ detail }) => setForm((f) => ({ ...f, description: detail.value }))} rows={3} />
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
          <FormField label="Frequency">
            <Select
              selectedOption={FREQUENCIES.find((f) => f.value === form.frequency) ?? null}
              options={FREQUENCIES}
              onChange={({ detail }) => setForm((f) => ({ ...f, frequency: detail.selectedOption.value ?? 'weekly' }))}
            />
          </FormField>
          {form.frequency === 'weekly' && (
            <FormField label="Day of Week">
              <Select
                selectedOption={DAYS_OF_WEEK.find((d) => d.value === form.day_of_week) ?? null}
                options={DAYS_OF_WEEK}
                onChange={({ detail }) => setForm((f) => ({ ...f, day_of_week: detail.selectedOption.value ?? '0' }))}
              />
            </FormField>
          )}
          {form.frequency === 'monthly' && (
            <FormField label="Day of Month" constraintText="1–28">
              <Input
                type="number"
                value={form.day_of_month}
                onChange={({ detail }) => setForm((f) => ({ ...f, day_of_month: detail.value }))}
              />
            </FormField>
          )}
        </SpaceBetween>
      </Modal>

      <ContentLayout
        header={
          <Header
            variant="h1"
            actions={
              canEdit && (
                <Button variant="primary" onClick={openCreate}>Create Rule</Button>
              )
            }
          >
            Recurring Tickets
          </Header>
        }
      >
        <Container>
          {error && <Alert type="error">{error}</Alert>}
          <Table
            columnDefinitions={[
              { id: 'name', header: 'Rule Name', cell: (r: RecurringTicketRule) => r.name },
              { id: 'subject', header: 'Subject', cell: (r: RecurringTicketRule) => r.subject },
              {
                id: 'frequency',
                header: 'Frequency',
                cell: (r: RecurringTicketRule) => {
                  const label = r.frequency.charAt(0).toUpperCase() + r.frequency.slice(1);
                  if (r.frequency === 'weekly' && r.day_of_week != null) {
                    const day = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][r.day_of_week] ?? '';
                    return `${label} (${day})`;
                  }
                  if (r.frequency === 'monthly' && r.day_of_month) {
                    return `${label} (day ${r.day_of_month})`;
                  }
                  return label;
                },
              },
              {
                id: 'priority',
                header: 'Priority',
                cell: (r: RecurringTicketRule) => (
                  <Badge color={r.priority === 'high' ? 'red' : r.priority === 'medium' ? 'blue' : 'grey'}>
                    {r.priority.charAt(0).toUpperCase() + r.priority.slice(1)}
                  </Badge>
                ),
              },
              { id: 'next_run', header: 'Next Run', cell: (r: RecurringTicketRule) => fmtDate(r.next_run_at) },
              { id: 'last_run', header: 'Last Run', cell: (r: RecurringTicketRule) => fmtDate(r.last_run_at) },
              ...(canEdit
                ? [{
                    id: 'active',
                    header: 'Active',
                    cell: (r: RecurringTicketRule) => (
                      <Toggle checked={r.is_active} onChange={() => handleToggle(r)} />
                    ),
                  },
                  {
                    id: 'actions',
                    header: '',
                    cell: (r: RecurringTicketRule) => (
                      <SpaceBetween direction="horizontal" size="xs">
                        <Button variant="inline-icon" iconName="edit" ariaLabel="Edit" onClick={() => openEdit(r)} />
                        <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => setDeleteTarget(r)} />
                      </SpaceBetween>
                    ),
                  }]
                : []),
            ]}
            items={rules}
            empty={
              <Box textAlign="center" color="inherit" padding="m">
                No recurring rules yet.{canEdit && ' Click "Create Rule" to get started.'}
              </Box>
            }
          />
        </Container>
      </ContentLayout>
    </>
  );
};

export default RecurringTicketsPage;
