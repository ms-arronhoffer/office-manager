import React, { useCallback, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Tabs from '@cloudscape-design/components/tabs';
import Table from '@cloudscape-design/components/table';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Toggle from '@cloudscape-design/components/toggle';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import { hqHvac, offices as officesApi } from '@/api';
import type {
  HeatPump,
  HeatPumpServiceLog,
  PmTask,
  PmLog,
  HvacIssue,
  MaintenanceContract,
  Backflow,
} from '@/types';

// ─── Helpers ──────────────────────────────────────────────────────────────────

type SelectOption = { label: string; value: string };

function formatDate(value?: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleDateString();
}

function formatCurrency(value?: number | null): string {
  if (value == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
}

// ─── Tab state shape ──────────────────────────────────────────────────────────

interface TabState<T> {
  data: T[] | null;
  loading: boolean;
  error: string | null;
  loaded: boolean;
}

function initialTabState<T>(): TabState<T> {
  return { data: null, loading: false, error: null, loaded: false };
}

// ─── Generic CRUD Modal Hook ─────────────────────────────────────────────────

function useCrudModal<T extends Record<string, unknown>>(defaults: T) {
  const [visible, setVisible] = useState(false);
  const [form, setForm] = useState<T>(defaults);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openCreate = () => {
    setForm({ ...defaults });
    setEditingId(null);
    setError(null);
    setVisible(true);
  };

  const openEdit = (id: string, data: Partial<T>) => {
    setForm({ ...defaults, ...data });
    setEditingId(id);
    setError(null);
    setVisible(true);
  };

  const close = () => {
    setVisible(false);
    setError(null);
  };

  const updateField = (key: keyof T, value: T[keyof T]) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  return { visible, form, editingId, saving, setSaving, error, setError, openCreate, openEdit, close, updateField, setForm };
}

// ─── Delete Confirmation Hook ────────────────────────────────────────────────

function useDeleteConfirm() {
  const [visible, setVisible] = useState(false);
  const [itemId, setItemId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const open = (id: string) => {
    setItemId(id);
    setVisible(true);
  };

  const close = () => {
    setVisible(false);
    setItemId(null);
  };

  return { visible, itemId, deleting, setDeleting, open, close };
}

// ─── Heat Pumps tab ───────────────────────────────────────────────────────────

const HeatPumpsTab: React.FC<{
  state: TabState<HeatPump>;
  onRefresh: () => void;
  officeOptions: SelectOption[];
}> = ({ state, onRefresh, officeOptions }) => {
  const modal = useCrudModal({ unit_id: '', location_desc: '', make: '', model: '', serial_number: '', install_year: '', notes: '' });
  const del = useDeleteConfirm();
  const [tabError, setTabError] = useState<string | null>(null);

  const handleSave = async () => {
    modal.setSaving(true);
    modal.setError(null);
    try {
      const data = {
        unit_id: modal.form.unit_id,
        location_desc: modal.form.location_desc || undefined,
        make: modal.form.make || undefined,
        model: modal.form.model || undefined,
        serial_number: modal.form.serial_number || undefined,
        install_year: modal.form.install_year ? Number(modal.form.install_year) : undefined,
        notes: modal.form.notes || undefined,
      };
      if (modal.editingId) {
        await hqHvac.updateHeatPump(modal.editingId, data);
      } else {
        await hqHvac.createHeatPump(data);
      }
      modal.close();
      onRefresh();
    } catch {
      modal.setError('Failed to save heat pump.');
    } finally {
      modal.setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!del.itemId) return;
    del.setDeleting(true);
    try {
      await hqHvac.deleteHeatPump(del.itemId);
      del.close();
      onRefresh();
    } catch {
      setTabError('Failed to delete heat pump.');
      del.close();
    } finally {
      del.setDeleting(false);
    }
  };

  if (state.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  if (state.error) return <Alert type="error">{state.error}</Alert>;

  const items = state.data ?? [];

  return (
    <>
      {tabError && <Alert type="error" dismissible onDismiss={() => setTabError(null)}>{tabError}</Alert>}
      <Table
        header={
          <Header variant="h2" counter={`(${items.length})`}
            actions={<Button variant="primary" onClick={modal.openCreate}>Add Heat Pump</Button>}
          >
            Heat Pumps
          </Header>
        }
        items={items}
        columnDefinitions={[
          { id: 'unit_id', header: 'Unit ID', cell: (r) => r.unit_id, width: 120 },
          { id: 'location', header: 'Location', cell: (r) => r.location_desc ?? '—', width: 200 },
          { id: 'make', header: 'Make', cell: (r) => r.make ?? '—', width: 130 },
          { id: 'model', header: 'Model', cell: (r) => r.model ?? '—', width: 130 },
          { id: 'serial', header: 'Serial #', cell: (r) => r.serial_number ?? '—', width: 140 },
          { id: 'year', header: 'Install Year', cell: (r) => r.install_year ?? '—', width: 110 },
          {
            id: 'actions', header: '', width: 120,
            cell: (r: HeatPump) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-icon" iconName="edit" ariaLabel="Edit"
                  onClick={() => modal.openEdit(r.id, { unit_id: r.unit_id, location_desc: r.location_desc ?? '', make: r.make ?? '', model: r.model ?? '', serial_number: r.serial_number ?? '', install_year: r.install_year?.toString() ?? '', notes: r.notes ?? '' })} />
                <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => del.open(r.id)} />
              </SpaceBetween>
            ),
          },
        ]}
        expandableRows={{
          getItemChildren: () => [],
          isItemExpandable: (item) => (item.service_logs?.length ?? 0) > 0,
          expandableRowContent: (item) => (
            <ExpandableSection headerText={`Service Logs (${item.service_logs?.length ?? 0})`} defaultExpanded>
              <Table
                variant="embedded"
                items={item.service_logs ?? []}
                columnDefinitions={[
                  { id: 'date', header: 'Date', cell: (r: HeatPumpServiceLog) => formatDate(r.service_date) },
                  { id: 'desc', header: 'Description', cell: (r: HeatPumpServiceLog) => r.description },
                  { id: 'invoice', header: 'Invoice #', cell: (r: HeatPumpServiceLog) => r.invoice_number ?? '—' },
                  { id: 'cost', header: 'Cost', cell: (r: HeatPumpServiceLog) => formatCurrency(r.cost) },
                ]}
                empty={<Box textAlign="center" color="text-body-secondary">No service logs</Box>}
              />
            </ExpandableSection>
          ),
        }}
        empty={<Box textAlign="center" color="text-body-secondary" padding="l">No heat pumps found</Box>}
        stickyColumns={{ last: 1 }}
      />

      <Modal visible={modal.visible} onDismiss={modal.close} header={modal.editingId ? 'Edit Heat Pump' : 'Add Heat Pump'}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={modal.close}>Cancel</Button>
          <Button variant="primary" onClick={handleSave} loading={modal.saving} disabled={!modal.form.unit_id.trim()}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {modal.error && <Alert type="error">{modal.error}</Alert>}
          <FormField label="Unit ID" constraintText="Required"><Input value={modal.form.unit_id} onChange={({ detail }) => modal.updateField('unit_id', detail.value)} /></FormField>
          <FormField label="Location">
            <Select
              selectedOption={modal.form.location_desc ? { label: modal.form.location_desc, value: modal.form.location_desc } : null}
              onChange={({ detail }) => modal.updateField('location_desc', detail.selectedOption?.value ?? '')}
              options={officeOptions}
              placeholder="Select office location"
            />
          </FormField>
          <FormField label="Make"><Input value={modal.form.make} onChange={({ detail }) => modal.updateField('make', detail.value)} /></FormField>
          <FormField label="Model"><Input value={modal.form.model} onChange={({ detail }) => modal.updateField('model', detail.value)} /></FormField>
          <FormField label="Serial Number"><Input value={modal.form.serial_number} onChange={({ detail }) => modal.updateField('serial_number', detail.value)} /></FormField>
          <FormField label="Install Year"><Input value={modal.form.install_year} onChange={({ detail }) => modal.updateField('install_year', detail.value)} type="number" /></FormField>
          <FormField label="Notes"><Textarea value={modal.form.notes} onChange={({ detail }) => modal.updateField('notes', detail.value)} rows={2} /></FormField>
        </SpaceBetween>
      </Modal>

      <Modal visible={del.visible} onDismiss={del.close} header="Delete Heat Pump"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={del.close}>Cancel</Button>
          <Button variant="primary" onClick={handleDelete} loading={del.deleting}>Delete</Button>
        </SpaceBetween></Box>}>
        Are you sure you want to delete this heat pump?
      </Modal>
    </>
  );
};

// ─── PM Tasks tab ─────────────────────────────────────────────────────────────

const PmTasksTab: React.FC<{
  state: TabState<PmTask>;
  onRefresh: () => void;
}> = ({ state, onRefresh }) => {
  const modal = useCrudModal({ equipment_category: '', equipment_id: '', task_description: '', frequency: '', can_in_house: false, last_pm_date: '', next_due_date: '', status: 'Not Started', notes: '' });
  const del = useDeleteConfirm();
  const [tabError, setTabError] = useState<string | null>(null);

  const handleSave = async () => {
    modal.setSaving(true);
    modal.setError(null);
    try {
      const data = {
        equipment_category: modal.form.equipment_category,
        equipment_id: modal.form.equipment_id || undefined,
        task_description: modal.form.task_description,
        frequency: modal.form.frequency || undefined,
        can_in_house: modal.form.can_in_house,
        last_pm_date: modal.form.last_pm_date || undefined,
        next_due_date: modal.form.next_due_date || undefined,
        status: modal.form.status,
        notes: modal.form.notes || undefined,
      };
      if (modal.editingId) {
        await hqHvac.updatePmTask(modal.editingId, data);
      } else {
        await hqHvac.createPmTask(data);
      }
      modal.close();
      onRefresh();
    } catch {
      modal.setError('Failed to save PM task.');
    } finally {
      modal.setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!del.itemId) return;
    del.setDeleting(true);
    try {
      await hqHvac.deletePmTask(del.itemId);
      del.close();
      onRefresh();
    } catch {
      setTabError('Failed to delete PM task.');
      del.close();
    } finally {
      del.setDeleting(false);
    }
  };

  if (state.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  if (state.error) return <Alert type="error">{state.error}</Alert>;

  const items = state.data ?? [];

  return (
    <>
      {tabError && <Alert type="error" dismissible onDismiss={() => setTabError(null)}>{tabError}</Alert>}
      <Table
        header={
          <Header variant="h2" counter={`(${items.length})`}
            actions={<Button variant="primary" onClick={modal.openCreate}>Add Task</Button>}>
            PM Tasks
          </Header>
        }
        items={items}
        columnDefinitions={[
          { id: 'task', header: 'Task', cell: (r) => r.task_description, width: 220 },
          { id: 'category', header: 'Category', cell: (r) => r.equipment_category, width: 140 },
          { id: 'frequency', header: 'Frequency', cell: (r) => r.frequency ?? '—', width: 120 },
          { id: 'in_house', header: 'In-House', cell: (r) => r.can_in_house ? 'Yes' : 'No', width: 100 },
          { id: 'last_pm', header: 'Last PM', cell: (r) => formatDate(r.last_pm_date), width: 110 },
          { id: 'next_due', header: 'Next Due', cell: (r) => formatDate(r.next_due_date), width: 110 },
          { id: 'status', header: 'Status', cell: (r) => r.status, width: 130 },
          { id: 'actions', header: '', width: 120,
            cell: (r: PmTask) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-icon" iconName="edit" ariaLabel="Edit"
                  onClick={() => modal.openEdit(r.id, { equipment_category: r.equipment_category, equipment_id: r.equipment_id ?? '', task_description: r.task_description, frequency: r.frequency ?? '', can_in_house: r.can_in_house, last_pm_date: r.last_pm_date ?? '', next_due_date: r.next_due_date ?? '', status: r.status, notes: r.notes ?? '' })} />
                <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => del.open(r.id)} />
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center" color="text-body-secondary" padding="l">No PM tasks found</Box>}
        stickyColumns={{ last: 1 }}
      />

      <Modal visible={modal.visible} onDismiss={modal.close} header={modal.editingId ? 'Edit PM Task' : 'Add PM Task'}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={modal.close}>Cancel</Button>
          <Button variant="primary" onClick={handleSave} loading={modal.saving} disabled={!modal.form.equipment_category.trim() || !modal.form.task_description.trim()}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {modal.error && <Alert type="error">{modal.error}</Alert>}
          <FormField label="Equipment Category" constraintText="Required"><Input value={modal.form.equipment_category} onChange={({ detail }) => modal.updateField('equipment_category', detail.value)} /></FormField>
          <FormField label="Equipment ID"><Input value={modal.form.equipment_id as string} onChange={({ detail }) => modal.updateField('equipment_id', detail.value)} /></FormField>
          <FormField label="Task Description" constraintText="Required"><Textarea value={modal.form.task_description} onChange={({ detail }) => modal.updateField('task_description', detail.value)} rows={2} /></FormField>
          <FormField label="Frequency"><Input value={modal.form.frequency} onChange={({ detail }) => modal.updateField('frequency', detail.value)} placeholder="e.g., Monthly, Quarterly" /></FormField>
          <FormField label="Can Do In-House"><Toggle checked={modal.form.can_in_house as boolean} onChange={({ detail }) => modal.updateField('can_in_house', detail.checked as never)} /></FormField>
          <FormField label="Last PM Date"><Input value={modal.form.last_pm_date} onChange={({ detail }) => modal.updateField('last_pm_date', detail.value)} type="date" /></FormField>
          <FormField label="Next Due Date"><Input value={modal.form.next_due_date} onChange={({ detail }) => modal.updateField('next_due_date', detail.value)} type="date" /></FormField>
          <FormField label="Status">
            <Select selectedOption={{ label: modal.form.status, value: modal.form.status }}
              onChange={({ detail }) => modal.updateField('status', (detail.selectedOption?.value ?? 'Not Started') as never)}
              options={[{ label: 'Not Started', value: 'Not Started' }, { label: 'In Progress', value: 'In Progress' }, { label: 'Completed', value: 'Completed' }]} />
          </FormField>
          <FormField label="Notes"><Textarea value={modal.form.notes} onChange={({ detail }) => modal.updateField('notes', detail.value)} rows={2} /></FormField>
        </SpaceBetween>
      </Modal>

      <Modal visible={del.visible} onDismiss={del.close} header="Delete PM Task"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={del.close}>Cancel</Button>
          <Button variant="primary" onClick={handleDelete} loading={del.deleting}>Delete</Button>
        </SpaceBetween></Box>}>
        Are you sure you want to delete this PM task?
      </Modal>
    </>
  );
};

// ─── PM Log tab ───────────────────────────────────────────────────────────────

const PmLogTab: React.FC<{
  state: TabState<PmLog>;
  onRefresh: () => void;
  officeOptions: SelectOption[];
}> = ({ state, onRefresh, officeOptions }) => {
  const modal = useCrudModal({ tech_name: '', date_of_visit: '', location: '', equipment_type: '', equipment_id: '', task: '', status: '', notes: '' });
  const del = useDeleteConfirm();
  const [tabError, setTabError] = useState<string | null>(null);

  const handleSave = async () => {
    modal.setSaving(true);
    modal.setError(null);
    try {
      const data = {
        tech_name: modal.form.tech_name || undefined,
        date_of_visit: modal.form.date_of_visit || undefined,
        location: modal.form.location || undefined,
        equipment_type: modal.form.equipment_type || undefined,
        equipment_id: modal.form.equipment_id || undefined,
        task: modal.form.task || undefined,
        status: modal.form.status || undefined,
        notes: modal.form.notes || undefined,
      };
      if (modal.editingId) {
        await hqHvac.updatePmLog(modal.editingId, data);
      } else {
        await hqHvac.createPmLog(data);
      }
      modal.close();
      onRefresh();
    } catch {
      modal.setError('Failed to save PM log entry.');
    } finally {
      modal.setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!del.itemId) return;
    del.setDeleting(true);
    try {
      await hqHvac.deletePmLog(del.itemId);
      del.close();
      onRefresh();
    } catch {
      setTabError('Failed to delete PM log entry.');
      del.close();
    } finally {
      del.setDeleting(false);
    }
  };

  if (state.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  if (state.error) return <Alert type="error">{state.error}</Alert>;

  const items = state.data ?? [];

  return (
    <>
      {tabError && <Alert type="error" dismissible onDismiss={() => setTabError(null)}>{tabError}</Alert>}
      <Table
        header={
          <Header variant="h2" counter={`(${items.length})`}
            actions={<Button variant="primary" onClick={modal.openCreate}>Add Log Entry</Button>}>
            PM Log
          </Header>
        }
        items={items}
        columnDefinitions={[
          { id: 'date', header: 'Date of Visit', cell: (r) => formatDate(r.date_of_visit), width: 130 },
          { id: 'tech', header: 'Technician', cell: (r) => r.tech_name ?? '—', width: 150 },
          { id: 'location', header: 'Location', cell: (r) => r.location ?? '—', width: 150 },
          { id: 'equipment', header: 'Equipment', cell: (r) => r.equipment_type ?? '—', width: 140 },
          { id: 'task', header: 'Task', cell: (r) => r.task ?? '—', width: 200 },
          { id: 'status', header: 'Status', cell: (r) => r.status ?? '—', width: 110 },
          { id: 'notes', header: 'Notes', cell: (r) => r.notes ?? '—', width: 180 },
          { id: 'actions', header: '', width: 120,
            cell: (r: PmLog) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-icon" iconName="edit" ariaLabel="Edit"
                  onClick={() => modal.openEdit(r.id, { tech_name: r.tech_name ?? '', date_of_visit: r.date_of_visit ?? '', location: r.location ?? '', equipment_type: r.equipment_type ?? '', equipment_id: r.equipment_id ?? '', task: r.task ?? '', status: r.status ?? '', notes: r.notes ?? '' })} />
                <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => del.open(r.id)} />
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center" color="text-body-secondary" padding="l">No PM log entries found</Box>}
        stickyColumns={{ last: 1 }}
      />

      <Modal visible={modal.visible} onDismiss={modal.close} header={modal.editingId ? 'Edit PM Log Entry' : 'Add PM Log Entry'}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={modal.close}>Cancel</Button>
          <Button variant="primary" onClick={handleSave} loading={modal.saving}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {modal.error && <Alert type="error">{modal.error}</Alert>}
          <FormField label="Technician"><Input value={modal.form.tech_name} onChange={({ detail }) => modal.updateField('tech_name', detail.value)} /></FormField>
          <FormField label="Date of Visit"><Input value={modal.form.date_of_visit} onChange={({ detail }) => modal.updateField('date_of_visit', detail.value)} type="date" /></FormField>
          <FormField label="Location">
            <Select
              selectedOption={modal.form.location ? { label: modal.form.location, value: modal.form.location } : null}
              onChange={({ detail }) => modal.updateField('location', detail.selectedOption?.value ?? '')}
              options={officeOptions}
              placeholder="Select office location"
            />
          </FormField>
          <FormField label="Equipment Type"><Input value={modal.form.equipment_type} onChange={({ detail }) => modal.updateField('equipment_type', detail.value)} /></FormField>
          <FormField label="Equipment ID"><Input value={modal.form.equipment_id} onChange={({ detail }) => modal.updateField('equipment_id', detail.value)} /></FormField>
          <FormField label="Task"><Textarea value={modal.form.task} onChange={({ detail }) => modal.updateField('task', detail.value)} rows={2} /></FormField>
          <FormField label="Status"><Input value={modal.form.status} onChange={({ detail }) => modal.updateField('status', detail.value)} /></FormField>
          <FormField label="Notes"><Textarea value={modal.form.notes} onChange={({ detail }) => modal.updateField('notes', detail.value)} rows={2} /></FormField>
        </SpaceBetween>
      </Modal>

      <Modal visible={del.visible} onDismiss={del.close} header="Delete PM Log Entry"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={del.close}>Cancel</Button>
          <Button variant="primary" onClick={handleDelete} loading={del.deleting}>Delete</Button>
        </SpaceBetween></Box>}>
        Are you sure you want to delete this PM log entry?
      </Modal>
    </>
  );
};

// ─── Issues tab ───────────────────────────────────────────────────────────────

const IssuesTab: React.FC<{
  state: TabState<HvacIssue>;
  onRefresh: () => void;
}> = ({ state, onRefresh }) => {
  const modal = useCrudModal({ description: '', issue_date: '', invoice_number: '', cost: '', status: 'open' });
  const del = useDeleteConfirm();
  const [tabError, setTabError] = useState<string | null>(null);

  const handleSave = async () => {
    modal.setSaving(true);
    modal.setError(null);
    try {
      const data = {
        description: modal.form.description,
        issue_date: modal.form.issue_date || undefined,
        invoice_number: modal.form.invoice_number || undefined,
        cost: modal.form.cost ? Number(modal.form.cost) : undefined,
        status: modal.form.status,
      };
      if (modal.editingId) {
        await hqHvac.updateIssue(modal.editingId, data);
      } else {
        await hqHvac.createIssue(data);
      }
      modal.close();
      onRefresh();
    } catch {
      modal.setError('Failed to save issue.');
    } finally {
      modal.setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!del.itemId) return;
    del.setDeleting(true);
    try {
      await hqHvac.deleteIssue(del.itemId);
      del.close();
      onRefresh();
    } catch {
      setTabError('Failed to delete issue.');
      del.close();
    } finally {
      del.setDeleting(false);
    }
  };

  if (state.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  if (state.error) return <Alert type="error">{state.error}</Alert>;

  const items = state.data ?? [];
  const totalCost = items.reduce((sum, r) => sum + (r.cost ?? 0), 0);

  return (
    <>
      {tabError && <Alert type="error" dismissible onDismiss={() => setTabError(null)}>{tabError}</Alert>}
      <Table
        header={
          <Header variant="h2" counter={`(${items.length})`}
            description={`Total cost: ${formatCurrency(totalCost)}`}
            actions={<Button variant="primary" onClick={modal.openCreate}>Create Issue</Button>}>
            Issues
          </Header>
        }
        items={items}
        columnDefinitions={[
          { id: 'date', header: 'Issue Date', cell: (r) => formatDate(r.issue_date), width: 120 },
          { id: 'description', header: 'Description', cell: (r) => r.description ?? '—', width: 260 },
          { id: 'invoice', header: 'Invoice #', cell: (r) => r.invoice_number ?? '—', width: 120 },
          { id: 'cost', header: 'Cost', cell: (r) => formatCurrency(r.cost), width: 100 },
          { id: 'status', header: 'Status', cell: (r) => r.status ?? '—', width: 100 },
          { id: 'actions', header: '', width: 120,
            cell: (r: HvacIssue) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-icon" iconName="edit" ariaLabel="Edit"
                  onClick={() => modal.openEdit(r.id, { description: r.description ?? '', issue_date: r.issue_date ?? '', invoice_number: r.invoice_number ?? '', cost: r.cost?.toString() ?? '', status: r.status ?? 'open' })} />
                <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => del.open(r.id)} />
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center" color="text-body-secondary" padding="l">No issues found</Box>}
        stickyColumns={{ last: 1 }}
      />

      <Modal visible={modal.visible} onDismiss={modal.close} header={modal.editingId ? 'Edit Issue' : 'Create Issue'}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={modal.close}>Cancel</Button>
          <Button variant="primary" onClick={handleSave} loading={modal.saving} disabled={!modal.form.description.trim()}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {modal.error && <Alert type="error">{modal.error}</Alert>}
          <FormField label="Description" constraintText="Required"><Textarea value={modal.form.description} onChange={({ detail }) => modal.updateField('description', detail.value)} rows={3} /></FormField>
          <FormField label="Issue Date"><Input value={modal.form.issue_date} onChange={({ detail }) => modal.updateField('issue_date', detail.value)} type="date" /></FormField>
          <FormField label="Invoice Number"><Input value={modal.form.invoice_number} onChange={({ detail }) => modal.updateField('invoice_number', detail.value)} /></FormField>
          <FormField label="Cost"><Input value={modal.form.cost} onChange={({ detail }) => modal.updateField('cost', detail.value)} type="number" /></FormField>
          <FormField label="Status">
            <Select selectedOption={{ label: modal.form.status, value: modal.form.status }}
              onChange={({ detail }) => modal.updateField('status', (detail.selectedOption?.value ?? 'open') as never)}
              options={[{ label: 'open', value: 'open' }, { label: 'closed', value: 'closed' }]} />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal visible={del.visible} onDismiss={del.close} header="Delete Issue"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={del.close}>Cancel</Button>
          <Button variant="primary" onClick={handleDelete} loading={del.deleting}>Delete</Button>
        </SpaceBetween></Box>}>
        Are you sure you want to delete this issue?
      </Modal>
    </>
  );
};

// ─── Maintenance Contracts tab ────────────────────────────────────────────────

const MaintenanceContractsTab: React.FC<{
  state: TabState<MaintenanceContract>;
  onRefresh: () => void;
}> = ({ state, onRefresh }) => {
  const modal = useCrudModal({ contractor_name: '', contract_start_date: '', cancellation_notice: '', equipment_covered: '', notes: '' });
  const del = useDeleteConfirm();
  const [tabError, setTabError] = useState<string | null>(null);

  const handleSave = async () => {
    modal.setSaving(true);
    modal.setError(null);
    try {
      const data = {
        contractor_name: modal.form.contractor_name || undefined,
        contract_start_date: modal.form.contract_start_date || undefined,
        cancellation_notice: modal.form.cancellation_notice || undefined,
        equipment_covered: modal.form.equipment_covered || undefined,
        notes: modal.form.notes || undefined,
      };
      if (modal.editingId) {
        await hqHvac.updateMaintenanceContract(modal.editingId, data);
      } else {
        await hqHvac.createMaintenanceContract(data);
      }
      modal.close();
      onRefresh();
    } catch {
      modal.setError('Failed to save maintenance contract.');
    } finally {
      modal.setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!del.itemId) return;
    del.setDeleting(true);
    try {
      await hqHvac.deleteMaintenanceContract(del.itemId);
      del.close();
      onRefresh();
    } catch {
      setTabError('Failed to delete maintenance contract.');
      del.close();
    } finally {
      del.setDeleting(false);
    }
  };

  if (state.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  if (state.error) return <Alert type="error">{state.error}</Alert>;

  const items = state.data ?? [];

  return (
    <>
      {tabError && <Alert type="error" dismissible onDismiss={() => setTabError(null)}>{tabError}</Alert>}
      <Table
        header={
          <Header variant="h2" counter={`(${items.length})`}
            actions={<Button variant="primary" onClick={modal.openCreate}>Add Contract</Button>}>
            Maintenance Contracts
          </Header>
        }
        items={items}
        columnDefinitions={[
          { id: 'contractor', header: 'Contractor', cell: (r) => r.contractor_name ?? '—', width: 180 },
          { id: 'start', header: 'Start Date', cell: (r) => formatDate(r.contract_start_date), width: 120 },
          { id: 'cancel', header: 'Cancellation Notice', cell: (r) => r.cancellation_notice ?? '—', width: 170 },
          { id: 'equipment', header: 'Equipment Covered', cell: (r) => r.equipment_covered ?? '—', width: 200 },
          { id: 'notes', header: 'Notes', cell: (r) => r.notes ?? '—', width: 180 },
          { id: 'actions', header: '', width: 120,
            cell: (r: MaintenanceContract) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-icon" iconName="edit" ariaLabel="Edit"
                  onClick={() => modal.openEdit(r.id, { contractor_name: r.contractor_name ?? '', contract_start_date: r.contract_start_date ?? '', cancellation_notice: r.cancellation_notice ?? '', equipment_covered: r.equipment_covered ?? '', notes: r.notes ?? '' })} />
                <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => del.open(r.id)} />
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center" color="text-body-secondary" padding="l">No maintenance contracts found</Box>}
        stickyColumns={{ last: 1 }}
      />

      <Modal visible={modal.visible} onDismiss={modal.close} header={modal.editingId ? 'Edit Contract' : 'Add Contract'}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={modal.close}>Cancel</Button>
          <Button variant="primary" onClick={handleSave} loading={modal.saving}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {modal.error && <Alert type="error">{modal.error}</Alert>}
          <FormField label="Contractor Name"><Input value={modal.form.contractor_name} onChange={({ detail }) => modal.updateField('contractor_name', detail.value)} /></FormField>
          <FormField label="Start Date"><Input value={modal.form.contract_start_date} onChange={({ detail }) => modal.updateField('contract_start_date', detail.value)} type="date" /></FormField>
          <FormField label="Cancellation Notice"><Input value={modal.form.cancellation_notice} onChange={({ detail }) => modal.updateField('cancellation_notice', detail.value)} /></FormField>
          <FormField label="Equipment Covered"><Textarea value={modal.form.equipment_covered} onChange={({ detail }) => modal.updateField('equipment_covered', detail.value)} rows={2} /></FormField>
          <FormField label="Notes"><Textarea value={modal.form.notes} onChange={({ detail }) => modal.updateField('notes', detail.value)} rows={2} /></FormField>
        </SpaceBetween>
      </Modal>

      <Modal visible={del.visible} onDismiss={del.close} header="Delete Maintenance Contract"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={del.close}>Cancel</Button>
          <Button variant="primary" onClick={handleDelete} loading={del.deleting}>Delete</Button>
        </SpaceBetween></Box>}>
        Are you sure you want to delete this maintenance contract?
      </Modal>
    </>
  );
};

// ─── Backflows tab ────────────────────────────────────────────────────────────

const BackflowsTab: React.FC<{
  state: TabState<Backflow>;
  onRefresh: () => void;
  officeOptions: SelectOption[];
}> = ({ state, onRefresh, officeOptions }) => {
  const modal = useCrudModal({ location_desc: '', replaced_year: '', last_tested_by: '', last_tested_year: '', reported_to: '', notes: '' });
  const del = useDeleteConfirm();
  const [tabError, setTabError] = useState<string | null>(null);

  const handleSave = async () => {
    modal.setSaving(true);
    modal.setError(null);
    try {
      const data = {
        location_desc: modal.form.location_desc,
        replaced_year: modal.form.replaced_year || undefined,
        last_tested_by: modal.form.last_tested_by || undefined,
        last_tested_year: modal.form.last_tested_year || undefined,
        reported_to: modal.form.reported_to || undefined,
        notes: modal.form.notes || undefined,
      };
      if (modal.editingId) {
        await hqHvac.updateBackflow(modal.editingId, data);
      } else {
        await hqHvac.createBackflow(data);
      }
      modal.close();
      onRefresh();
    } catch {
      modal.setError('Failed to save backflow.');
    } finally {
      modal.setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!del.itemId) return;
    del.setDeleting(true);
    try {
      await hqHvac.deleteBackflow(del.itemId);
      del.close();
      onRefresh();
    } catch {
      setTabError('Failed to delete backflow.');
      del.close();
    } finally {
      del.setDeleting(false);
    }
  };

  if (state.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  if (state.error) return <Alert type="error">{state.error}</Alert>;

  const items = state.data ?? [];

  return (
    <>
      {tabError && <Alert type="error" dismissible onDismiss={() => setTabError(null)}>{tabError}</Alert>}
      <Table
        header={
          <Header variant="h2" counter={`(${items.length})`}
            actions={<Button variant="primary" onClick={modal.openCreate}>Add Backflow</Button>}>
            Backflow Devices
          </Header>
        }
        items={items}
        columnDefinitions={[
          { id: 'location', header: 'Location', cell: (r) => r.location_desc ?? '—', width: 200 },
          { id: 'replaced', header: 'Replaced Year', cell: (r) => r.replaced_year ?? '—', width: 130 },
          { id: 'tested_by', header: 'Last Tested By', cell: (r) => r.last_tested_by ?? '—', width: 150 },
          { id: 'tested_year', header: 'Last Tested Year', cell: (r) => r.last_tested_year ?? '—', width: 140 },
          { id: 'reported_to', header: 'Reported To', cell: (r) => r.reported_to ?? '—', width: 140 },
          { id: 'notes', header: 'Notes', cell: (r) => r.notes ?? '—', width: 180 },
          { id: 'actions', header: '', width: 120,
            cell: (r: Backflow) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-icon" iconName="edit" ariaLabel="Edit"
                  onClick={() => modal.openEdit(r.id, { location_desc: r.location_desc ?? '', replaced_year: (r.replaced_year ?? '').toString(), last_tested_by: r.last_tested_by ?? '', last_tested_year: (r.last_tested_year ?? '').toString(), reported_to: r.reported_to ?? '', notes: r.notes ?? '' })} />
                <Button variant="inline-icon" iconName="remove" ariaLabel="Delete" onClick={() => del.open(r.id)} />
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center" color="text-body-secondary" padding="l">No backflow devices found</Box>}
        stickyColumns={{ last: 1 }}
      />

      <Modal visible={modal.visible} onDismiss={modal.close} header={modal.editingId ? 'Edit Backflow' : 'Add Backflow'}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={modal.close}>Cancel</Button>
          <Button variant="primary" onClick={handleSave} loading={modal.saving} disabled={!modal.form.location_desc.trim()}>Save</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {modal.error && <Alert type="error">{modal.error}</Alert>}
          <FormField label="Location" constraintText="Required">
            <Select
              selectedOption={modal.form.location_desc ? { label: modal.form.location_desc, value: modal.form.location_desc } : null}
              onChange={({ detail }) => modal.updateField('location_desc', detail.selectedOption?.value ?? '')}
              options={officeOptions}
              placeholder="Select office location"
            />
          </FormField>
          <FormField label="Replaced Year"><Input value={modal.form.replaced_year} onChange={({ detail }) => modal.updateField('replaced_year', detail.value)} /></FormField>
          <FormField label="Last Tested By"><Input value={modal.form.last_tested_by} onChange={({ detail }) => modal.updateField('last_tested_by', detail.value)} /></FormField>
          <FormField label="Last Tested Year"><Input value={modal.form.last_tested_year} onChange={({ detail }) => modal.updateField('last_tested_year', detail.value)} /></FormField>
          <FormField label="Reported To"><Input value={modal.form.reported_to} onChange={({ detail }) => modal.updateField('reported_to', detail.value)} /></FormField>
          <FormField label="Notes"><Textarea value={modal.form.notes} onChange={({ detail }) => modal.updateField('notes', detail.value)} rows={2} /></FormField>
        </SpaceBetween>
      </Modal>

      <Modal visible={del.visible} onDismiss={del.close} header="Delete Backflow"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={del.close}>Cancel</Button>
          <Button variant="primary" onClick={handleDelete} loading={del.deleting}>Delete</Button>
        </SpaceBetween></Box>}>
        Are you sure you want to delete this backflow device?
      </Modal>
    </>
  );
};

// ─── Page ─────────────────────────────────────────────────────────────────────

type TabId = 'heat-pumps' | 'pm-tasks' | 'pm-log' | 'issues' | 'maintenance-contracts' | 'backflows';

const HqHvacPage: React.FC = () => {
  const [activeTabId, setActiveTabId] = useState<TabId>('heat-pumps');
  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);

  React.useEffect(() => {
    officesApi.list({ page_size: 1000 }).then((res) => {
      setOfficeOptions(
        res.data.items.map((o) => ({ label: o.location_name, value: o.location_name })),
      );
    });
  }, []);

  const [heatPumpsState, setHeatPumpsState] = useState<TabState<HeatPump>>(initialTabState);
  const [pmTasksState, setPmTasksState] = useState<TabState<PmTask>>(initialTabState);
  const [pmLogState, setPmLogState] = useState<TabState<PmLog>>(initialTabState);
  const [issuesState, setIssuesState] = useState<TabState<HvacIssue>>(initialTabState);
  const [contractsState, setContractsState] = useState<TabState<MaintenanceContract>>(initialTabState);
  const [backflowsState, setBackflowsState] = useState<TabState<Backflow>>(initialTabState);

  const loadTab = useCallback(async (tabId: TabId) => {
    switch (tabId) {
      case 'heat-pumps': {
        setHeatPumpsState((s) => ({ ...s, loading: true, error: null }));
        try {
          const res = await hqHvac.getHeatPumps();
          setHeatPumpsState({ data: res.data, loading: false, error: null, loaded: true });
        } catch {
          setHeatPumpsState((s) => ({ ...s, loading: false, error: 'Failed to load heat pumps.' }));
        }
        break;
      }
      case 'pm-tasks': {
        setPmTasksState((s) => ({ ...s, loading: true, error: null }));
        try {
          const res = await hqHvac.getPmTasks();
          setPmTasksState({ data: res.data, loading: false, error: null, loaded: true });
        } catch {
          setPmTasksState((s) => ({ ...s, loading: false, error: 'Failed to load PM tasks.' }));
        }
        break;
      }
      case 'pm-log': {
        setPmLogState((s) => ({ ...s, loading: true, error: null }));
        try {
          const res = await hqHvac.getPmLog();
          setPmLogState({ data: res.data, loading: false, error: null, loaded: true });
        } catch {
          setPmLogState((s) => ({ ...s, loading: false, error: 'Failed to load PM log.' }));
        }
        break;
      }
      case 'issues': {
        setIssuesState((s) => ({ ...s, loading: true, error: null }));
        try {
          const res = await hqHvac.getIssues();
          setIssuesState({ data: res.data, loading: false, error: null, loaded: true });
        } catch {
          setIssuesState((s) => ({ ...s, loading: false, error: 'Failed to load issues.' }));
        }
        break;
      }
      case 'maintenance-contracts': {
        setContractsState((s) => ({ ...s, loading: true, error: null }));
        try {
          const res = await hqHvac.getMaintenanceContracts();
          setContractsState({ data: res.data, loading: false, error: null, loaded: true });
        } catch {
          setContractsState((s) => ({ ...s, loading: false, error: 'Failed to load maintenance contracts.' }));
        }
        break;
      }
      case 'backflows': {
        setBackflowsState((s) => ({ ...s, loading: true, error: null }));
        try {
          const res = await hqHvac.getBackflows();
          setBackflowsState({ data: res.data, loading: false, error: null, loaded: true });
        } catch {
          setBackflowsState((s) => ({ ...s, loading: false, error: 'Failed to load backflow devices.' }));
        }
        break;
      }
    }
  }, []);

  const handleTabChange = useCallback(
    ({ detail }: { detail: { activeTabId: string } }) => {
      const tab = detail.activeTabId as TabId;
      setActiveTabId(tab);

      const stateMap: Record<TabId, TabState<unknown>> = {
        'heat-pumps': heatPumpsState,
        'pm-tasks': pmTasksState,
        'pm-log': pmLogState,
        issues: issuesState,
        'maintenance-contracts': contractsState,
        backflows: backflowsState,
      };

      if (!stateMap[tab].loaded && !stateMap[tab].loading) {
        loadTab(tab);
      }
    },
    [heatPumpsState, pmTasksState, pmLogState, issuesState, contractsState, backflowsState, loadTab],
  );

  React.useEffect(() => {
    loadTab('heat-pumps');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshActive = useCallback(() => loadTab(activeTabId), [activeTabId, loadTab]);

  return (
    <ContentLayout header={<Header variant="h1">HVAC Systems</Header>}>
      <SpaceBetween size="l">
        <Tabs
          activeTabId={activeTabId}
          onChange={handleTabChange}
          tabs={[
            {
              id: 'heat-pumps', label: 'Heat Pumps',
              content: <Box padding={{ top: 'm' }}><HeatPumpsTab state={heatPumpsState} onRefresh={refreshActive} officeOptions={officeOptions} /></Box>,
            },
            {
              id: 'pm-tasks', label: 'PM Tasks',
              content: <Box padding={{ top: 'm' }}><PmTasksTab state={pmTasksState} onRefresh={refreshActive} /></Box>,
            },
            {
              id: 'pm-log', label: 'PM Log',
              content: <Box padding={{ top: 'm' }}><PmLogTab state={pmLogState} onRefresh={refreshActive} officeOptions={officeOptions} /></Box>,
            },
            {
              id: 'issues', label: 'Issues',
              content: <Box padding={{ top: 'm' }}><IssuesTab state={issuesState} onRefresh={refreshActive} /></Box>,
            },
            {
              id: 'maintenance-contracts', label: 'Maintenance Contracts',
              content: <Box padding={{ top: 'm' }}><MaintenanceContractsTab state={contractsState} onRefresh={refreshActive} /></Box>,
            },
            {
              id: 'backflows', label: 'Backflows',
              content: <Box padding={{ top: 'm' }}><BackflowsTab state={backflowsState} onRefresh={refreshActive} officeOptions={officeOptions} /></Box>,
            },
          ]}
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default HqHvacPage;
