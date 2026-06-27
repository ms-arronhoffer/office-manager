import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Toggle from '@cloudscape-design/components/toggle';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { maintenance as maintApi } from '@/api';
import type {
  MaintenanceAsset,
  MaintenanceTask,
  MaintenanceLog,
  MaintenanceCatalogCategory,
} from '@/types';

interface Option { label: string; value: string; }

interface Props {
  category: MaintenanceCatalogCategory;
  frequencies: string[];
  taskStatuses: string[];
  assetStatuses: string[];
  vendorOptions: Option[];
  officeOptions: Option[];
  canEdit: boolean;
  onChanged?: () => void;
}

const NONE = '';

const freqLabel = (f: string) =>
  f.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const fmtDate = (d: string | null | undefined) => (d ? d : '—');

const taskStatusBadge = (s: string) => {
  if (s === 'overdue') return <Badge color="red">OVERDUE</Badge>;
  if (s === 'due_soon') return <Badge color="blue">DUE SOON</Badge>;
  if (s === 'completed') return <Badge color="green">COMPLETED</Badge>;
  if (s === 'in_progress') return <Badge color="grey">IN PROGRESS</Badge>;
  if (s === 'on_hold') return <Badge color="grey">ON HOLD</Badge>;
  return <Badge color="grey">{s.replace(/_/g, ' ').toUpperCase()}</Badge>;
};

const emptyTaskForm = (category: string) => ({
  id: null as string | null,
  category,
  subtopic: NONE,
  office_id: NONE,
  vendor_id: NONE,
  title: '',
  description: '',
  frequency: NONE,
  last_completed_date: '',
  next_due_date: '',
  status: 'scheduled',
  is_regulatory: false,
  reminder_enabled: false,
  reminder_days_before: '14',
  reminder_recipients: '',
  notes: '',
});

const emptyAssetForm = (category: string) => ({
  id: null as string | null,
  category,
  subtopic: NONE,
  office_id: NONE,
  vendor_id: NONE,
  name: '',
  location_desc: '',
  make: '',
  model: '',
  serial_number: '',
  install_date: '',
  is_regulatory: false,
  certification_expiry: '',
  status: 'active',
  notes: '',
});

const emptyLogForm = () => ({
  service_date: '',
  performed_by: '',
  vendor_id: NONE,
  cost: '',
  invoice_number: '',
  description: '',
});

const MaintenanceCategoryPanel: React.FC<Props> = ({
  category,
  frequencies,
  taskStatuses,
  assetStatuses,
  vendorOptions,
  officeOptions,
  canEdit,
  onChanged,
}) => {
  const { addFlash } = useFlashbar();
  const [tasks, setTasks] = useState<MaintenanceTask[]>([]);
  const [assets, setAssets] = useState<MaintenanceAsset[]>([]);
  const [loading, setLoading] = useState(true);

  const subtopicOptions = useMemo<Option[]>(
    () => category.subtopics.map((s) => ({ label: s.label, value: s.value })),
    [category],
  );
  const subtopicLabel = useCallback(
    (v: string | null) => category.subtopics.find((s) => s.value === v)?.label ?? '—',
    [category],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tRes, aRes] = await Promise.all([
        maintApi.listTasks({ category: category.value }),
        maintApi.listAssets({ category: category.value }),
      ]);
      setTasks(tRes.data);
      setAssets(aRes.data);
    } catch {
      addFlash({ type: 'error', content: `Failed to load ${category.label}.` });
    } finally {
      setLoading(false);
    }
  }, [category, addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = useCallback(() => {
    load();
    onChanged?.();
  }, [load, onChanged]);

  // ── Task modal ──────────────────────────────────────────────────────────────
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [taskForm, setTaskForm] = useState(emptyTaskForm(category.value));
  const [savingTask, setSavingTask] = useState(false);

  const openNewTask = () => {
    setTaskForm(emptyTaskForm(category.value));
    setTaskModalOpen(true);
  };
  const openEditTask = (t: MaintenanceTask) => {
    setTaskForm({
      id: t.id,
      category: t.category,
      subtopic: t.subtopic ?? NONE,
      office_id: t.office_id ?? NONE,
      vendor_id: t.vendor_id ?? NONE,
      title: t.title,
      description: t.description ?? '',
      frequency: t.frequency ?? NONE,
      last_completed_date: t.last_completed_date ?? '',
      next_due_date: t.next_due_date ?? '',
      status: t.status,
      is_regulatory: t.is_regulatory,
      reminder_enabled: t.reminder_enabled,
      reminder_days_before: String(t.reminder_days_before ?? 14),
      reminder_recipients: (t.reminder_recipients ?? []).join(', '),
      notes: t.notes ?? '',
    });
    setTaskModalOpen(true);
  };

  const saveTask = async () => {
    if (!taskForm.title.trim()) {
      addFlash({ type: 'error', content: 'Task title is required.' });
      return;
    }
    setSavingTask(true);
    try {
      const payload: Partial<MaintenanceTask> = {
        category: category.value,
        subtopic: taskForm.subtopic || null,
        office_id: taskForm.office_id || null,
        vendor_id: taskForm.vendor_id || null,
        title: taskForm.title.trim(),
        description: taskForm.description || null,
        frequency: taskForm.frequency || null,
        last_completed_date: taskForm.last_completed_date || null,
        next_due_date: taskForm.next_due_date || null,
        status: taskForm.status,
        is_regulatory: taskForm.is_regulatory,
        reminder_enabled: taskForm.reminder_enabled,
        reminder_days_before: Number(taskForm.reminder_days_before) || 0,
        reminder_recipients: taskForm.reminder_recipients
          .split(',')
          .map((e) => e.trim())
          .filter(Boolean),
        notes: taskForm.notes || null,
      };
      if (taskForm.id) {
        await maintApi.updateTask(taskForm.id, payload);
        addFlash({ type: 'success', content: 'Task updated.' });
      } else {
        await maintApi.createTask(payload);
        addFlash({ type: 'success', content: 'Task created.' });
      }
      setTaskModalOpen(false);
      refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save task.' });
    } finally {
      setSavingTask(false);
    }
  };

  const deleteTask = async (id: string) => {
    try {
      await maintApi.deleteTask(id);
      addFlash({ type: 'success', content: 'Task deleted.' });
      refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete task.' });
    }
  };

  // ── Asset modal ─────────────────────────────────────────────────────────────
  const [assetModalOpen, setAssetModalOpen] = useState(false);
  const [assetForm, setAssetForm] = useState(emptyAssetForm(category.value));
  const [savingAsset, setSavingAsset] = useState(false);

  const openNewAsset = () => {
    setAssetForm(emptyAssetForm(category.value));
    setAssetModalOpen(true);
  };
  const openEditAsset = (a: MaintenanceAsset) => {
    setAssetForm({
      id: a.id,
      category: a.category,
      subtopic: a.subtopic ?? NONE,
      office_id: a.office_id ?? NONE,
      vendor_id: a.vendor_id ?? NONE,
      name: a.name,
      location_desc: a.location_desc ?? '',
      make: a.make ?? '',
      model: a.model ?? '',
      serial_number: a.serial_number ?? '',
      install_date: a.install_date ?? '',
      is_regulatory: a.is_regulatory,
      certification_expiry: a.certification_expiry ?? '',
      status: a.status,
      notes: a.notes ?? '',
    });
    setAssetModalOpen(true);
  };

  const saveAsset = async () => {
    if (!assetForm.name.trim()) {
      addFlash({ type: 'error', content: 'Asset name is required.' });
      return;
    }
    setSavingAsset(true);
    try {
      const payload: Partial<MaintenanceAsset> = {
        category: category.value,
        subtopic: assetForm.subtopic || null,
        office_id: assetForm.office_id || null,
        vendor_id: assetForm.vendor_id || null,
        name: assetForm.name.trim(),
        location_desc: assetForm.location_desc || null,
        make: assetForm.make || null,
        model: assetForm.model || null,
        serial_number: assetForm.serial_number || null,
        install_date: assetForm.install_date || null,
        is_regulatory: assetForm.is_regulatory,
        certification_expiry: assetForm.certification_expiry || null,
        status: assetForm.status,
        notes: assetForm.notes || null,
      };
      if (assetForm.id) {
        await maintApi.updateAsset(assetForm.id, payload);
        addFlash({ type: 'success', content: 'Asset updated.' });
      } else {
        await maintApi.createAsset(payload);
        addFlash({ type: 'success', content: 'Asset created.' });
      }
      setAssetModalOpen(false);
      refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save asset.' });
    } finally {
      setSavingAsset(false);
    }
  };

  const deleteAsset = async (id: string) => {
    try {
      await maintApi.deleteAsset(id);
      addFlash({ type: 'success', content: 'Asset deleted.' });
      refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete asset.' });
    }
  };

  // ── Service-log modal ──────────────────────────────────────────────────────
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logTask, setLogTask] = useState<MaintenanceTask | null>(null);
  const [logForm, setLogForm] = useState(emptyLogForm());
  const [logHistory, setLogHistory] = useState<MaintenanceLog[]>([]);
  const [savingLog, setSavingLog] = useState(false);

  const openLog = async (t: MaintenanceTask) => {
    setLogTask(t);
    setLogForm({ ...emptyLogForm(), vendor_id: t.vendor_id ?? NONE });
    setLogModalOpen(true);
    try {
      const res = await maintApi.listLogs({ task_id: t.id });
      setLogHistory(res.data);
    } catch {
      setLogHistory([]);
    }
  };

  const saveLog = async () => {
    if (!logTask) return;
    if (!logForm.description.trim()) {
      addFlash({ type: 'error', content: 'A description is required.' });
      return;
    }
    setSavingLog(true);
    try {
      await maintApi.createLog({
        task_id: logTask.id,
        asset_id: logTask.asset_id ?? null,
        service_date: logForm.service_date || null,
        performed_by: logForm.performed_by || null,
        vendor_id: logForm.vendor_id || null,
        cost: logForm.cost ? Number(logForm.cost) : null,
        invoice_number: logForm.invoice_number || null,
        description: logForm.description.trim(),
      });
      addFlash({ type: 'success', content: 'Service logged.' });
      setLogModalOpen(false);
      refresh();
    } catch {
      addFlash({ type: 'error', content: 'Failed to log service.' });
    } finally {
      setSavingLog(false);
    }
  };

  const vendorSelect = (value: string, onChange: (v: string) => void) => (
    <Select
      selectedOption={
        value ? vendorOptions.find((o) => o.value === value) ?? null : { label: 'Unassigned', value: NONE }
      }
      onChange={({ detail }) => onChange(detail.selectedOption.value ?? NONE)}
      options={[{ label: 'Unassigned', value: NONE }, ...vendorOptions]}
      filteringType="auto"
      placeholder="Assign a vendor"
    />
  );

  const officeSelect = (value: string, onChange: (v: string) => void) => (
    <Select
      selectedOption={
        value ? officeOptions.find((o) => o.value === value) ?? null : { label: 'None', value: NONE }
      }
      onChange={({ detail }) => onChange(detail.selectedOption.value ?? NONE)}
      options={[{ label: 'None', value: NONE }, ...officeOptions]}
      filteringType="auto"
      placeholder="Select a property"
    />
  );

  const subtopicSelect = (value: string, onChange: (v: string) => void) => (
    <Select
      selectedOption={
        value ? subtopicOptions.find((o) => o.value === value) ?? null : { label: 'None', value: NONE }
      }
      onChange={({ detail }) => onChange(detail.selectedOption.value ?? NONE)}
      options={[{ label: 'None', value: NONE }, ...subtopicOptions]}
      placeholder="Select a topic"
    />
  );

  return (
    <SpaceBetween size="l">
      <Container
        header={
          <Header
            variant="h2"
            counter={`(${tasks.length})`}
            actions={
              canEdit ? (
                <Button variant="primary" iconName="add-plus" onClick={openNewTask}>
                  Add task
                </Button>
              ) : undefined
            }
            description="Recurring maintenance obligations, assigned vendors and reminders."
          >
            Maintenance Tasks
          </Header>
        }
      >
        <Table
          variant="embedded"
          loading={loading}
          items={tasks}
          empty={<Box textAlign="center" color="inherit" padding="m">No tasks yet.</Box>}
          columnDefinitions={[
            { id: 'title', header: 'Task', cell: (r) => r.title },
            { id: 'subtopic', header: 'Topic', cell: (r) => subtopicLabel(r.subtopic) },
            { id: 'office', header: 'Property', cell: (r) => r.office?.location_name ?? '—' },
            { id: 'vendor', header: 'Vendor', cell: (r) => r.vendor?.company_name ?? 'Unassigned' },
            { id: 'frequency', header: 'Frequency', cell: (r) => (r.frequency ? freqLabel(r.frequency) : '—') },
            { id: 'next_due', header: 'Next Due', cell: (r) => fmtDate(r.next_due_date) },
            { id: 'status', header: 'Status', cell: (r) => taskStatusBadge(r.computed_status || r.status) },
            { id: 'reminder', header: 'Reminder', cell: (r) => (r.reminder_enabled ? `${r.reminder_days_before}d` : 'Off') },
            {
              id: 'actions',
              header: '',
              cell: (r) =>
                canEdit ? (
                  <SpaceBetween size="xs" direction="horizontal">
                    <Button variant="inline-link" onClick={() => openLog(r)}>Log</Button>
                    <Button variant="inline-link" onClick={() => openEditTask(r)}>Edit</Button>
                    <Button variant="inline-link" onClick={() => deleteTask(r.id)}>Delete</Button>
                  </SpaceBetween>
                ) : null,
            },
          ]}
        />
      </Container>

      <Container
        header={
          <Header
            variant="h2"
            counter={`(${assets.length})`}
            actions={
              canEdit ? (
                <Button iconName="add-plus" onClick={openNewAsset}>
                  Add asset
                </Button>
              ) : undefined
            }
            description="Equipment and structures serviced under this category."
          >
            Assets
          </Header>
        }
      >
        <Table
          variant="embedded"
          loading={loading}
          items={assets}
          empty={<Box textAlign="center" color="inherit" padding="m">No assets yet.</Box>}
          columnDefinitions={[
            { id: 'name', header: 'Name', cell: (r) => r.name },
            { id: 'subtopic', header: 'Topic', cell: (r) => subtopicLabel(r.subtopic) },
            { id: 'office', header: 'Property', cell: (r) => r.office?.location_name ?? '—' },
            { id: 'location', header: 'Location', cell: (r) => r.location_desc ?? '—' },
            { id: 'vendor', header: 'Vendor', cell: (r) => r.vendor?.company_name ?? '—' },
            { id: 'cert', header: 'Cert Expiry', cell: (r) => fmtDate(r.certification_expiry) },
            { id: 'status', header: 'Status', cell: (r) => r.status.replace(/_/g, ' ') },
            {
              id: 'actions',
              header: '',
              cell: (r) =>
                canEdit ? (
                  <SpaceBetween size="xs" direction="horizontal">
                    <Button variant="inline-link" onClick={() => openEditAsset(r)}>Edit</Button>
                    <Button variant="inline-link" onClick={() => deleteAsset(r.id)}>Delete</Button>
                  </SpaceBetween>
                ) : null,
            },
          ]}
        />
      </Container>

      {/* Task modal */}
      <Modal
        visible={taskModalOpen}
        onDismiss={() => setTaskModalOpen(false)}
        header={taskForm.id ? 'Edit task' : 'New task'}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setTaskModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingTask} onClick={saveTask}>Save</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Title" constraintText="Required">
            <Input value={taskForm.title} onChange={({ detail }) => setTaskForm((f) => ({ ...f, title: detail.value }))} />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Topic">{subtopicSelect(taskForm.subtopic, (v) => setTaskForm((f) => ({ ...f, subtopic: v })))}</FormField>
            <FormField label="Property">{officeSelect(taskForm.office_id, (v) => setTaskForm((f) => ({ ...f, office_id: v })))}</FormField>
            <FormField label="Vendor">{vendorSelect(taskForm.vendor_id, (v) => setTaskForm((f) => ({ ...f, vendor_id: v })))}</FormField>
            <FormField label="Frequency">
              <Select
                selectedOption={taskForm.frequency ? { label: freqLabel(taskForm.frequency), value: taskForm.frequency } : { label: 'None', value: NONE }}
                onChange={({ detail }) => setTaskForm((f) => ({ ...f, frequency: detail.selectedOption.value ?? NONE }))}
                options={[{ label: 'None', value: NONE }, ...frequencies.map((fr) => ({ label: freqLabel(fr), value: fr }))]}
              />
            </FormField>
            <FormField label="Last completed">
              <Input type="text" placeholder="YYYY-MM-DD" value={taskForm.last_completed_date} onChange={({ detail }) => setTaskForm((f) => ({ ...f, last_completed_date: detail.value }))} />
            </FormField>
            <FormField label="Next due">
              <Input type="text" placeholder="YYYY-MM-DD" value={taskForm.next_due_date} onChange={({ detail }) => setTaskForm((f) => ({ ...f, next_due_date: detail.value }))} />
            </FormField>
            <FormField label="Status">
              <Select
                selectedOption={{ label: taskForm.status.replace(/_/g, ' '), value: taskForm.status }}
                onChange={({ detail }) => setTaskForm((f) => ({ ...f, status: detail.selectedOption.value ?? 'scheduled' }))}
                options={taskStatuses.map((s) => ({ label: s.replace(/_/g, ' '), value: s }))}
              />
            </FormField>
            <FormField label="Regulatory / mandated">
              <Toggle checked={taskForm.is_regulatory} onChange={({ detail }) => setTaskForm((f) => ({ ...f, is_regulatory: detail.checked }))}>Required by code</Toggle>
            </FormField>
          </ColumnLayout>
          <FormField label="Description">
            <Textarea value={taskForm.description} onChange={({ detail }) => setTaskForm((f) => ({ ...f, description: detail.value }))} />
          </FormField>
          <FormField label="Email reminder">
            <Toggle checked={taskForm.reminder_enabled} onChange={({ detail }) => setTaskForm((f) => ({ ...f, reminder_enabled: detail.checked }))}>
              Send a reminder before the due date
            </Toggle>
          </FormField>
          {taskForm.reminder_enabled && (
            <ColumnLayout columns={2}>
              <FormField label="Days before due">
                <Input type="number" value={taskForm.reminder_days_before} onChange={({ detail }) => setTaskForm((f) => ({ ...f, reminder_days_before: detail.value }))} />
              </FormField>
              <FormField label="Recipients" description="Comma-separated emails. The assigned vendor is always notified.">
                <Input value={taskForm.reminder_recipients} onChange={({ detail }) => setTaskForm((f) => ({ ...f, reminder_recipients: detail.value }))} />
              </FormField>
            </ColumnLayout>
          )}
          <FormField label="Notes">
            <Textarea value={taskForm.notes} onChange={({ detail }) => setTaskForm((f) => ({ ...f, notes: detail.value }))} />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Asset modal */}
      <Modal
        visible={assetModalOpen}
        onDismiss={() => setAssetModalOpen(false)}
        header={assetForm.id ? 'Edit asset' : 'New asset'}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setAssetModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingAsset} onClick={saveAsset}>Save</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Name" constraintText="Required">
            <Input value={assetForm.name} onChange={({ detail }) => setAssetForm((f) => ({ ...f, name: detail.value }))} />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Topic">{subtopicSelect(assetForm.subtopic, (v) => setAssetForm((f) => ({ ...f, subtopic: v })))}</FormField>
            <FormField label="Property">{officeSelect(assetForm.office_id, (v) => setAssetForm((f) => ({ ...f, office_id: v })))}</FormField>
            <FormField label="Vendor">{vendorSelect(assetForm.vendor_id, (v) => setAssetForm((f) => ({ ...f, vendor_id: v })))}</FormField>
            <FormField label="Location">
              <Input value={assetForm.location_desc} onChange={({ detail }) => setAssetForm((f) => ({ ...f, location_desc: detail.value }))} />
            </FormField>
            <FormField label="Make"><Input value={assetForm.make} onChange={({ detail }) => setAssetForm((f) => ({ ...f, make: detail.value }))} /></FormField>
            <FormField label="Model"><Input value={assetForm.model} onChange={({ detail }) => setAssetForm((f) => ({ ...f, model: detail.value }))} /></FormField>
            <FormField label="Serial #"><Input value={assetForm.serial_number} onChange={({ detail }) => setAssetForm((f) => ({ ...f, serial_number: detail.value }))} /></FormField>
            <FormField label="Install date"><Input placeholder="YYYY-MM-DD" value={assetForm.install_date} onChange={({ detail }) => setAssetForm((f) => ({ ...f, install_date: detail.value }))} /></FormField>
            <FormField label="Status">
              <Select
                selectedOption={{ label: assetForm.status.replace(/_/g, ' '), value: assetForm.status }}
                onChange={({ detail }) => setAssetForm((f) => ({ ...f, status: detail.selectedOption.value ?? 'active' }))}
                options={assetStatuses.map((s) => ({ label: s.replace(/_/g, ' '), value: s }))}
              />
            </FormField>
            <FormField label="Certification expiry"><Input placeholder="YYYY-MM-DD" value={assetForm.certification_expiry} onChange={({ detail }) => setAssetForm((f) => ({ ...f, certification_expiry: detail.value }))} /></FormField>
            <FormField label="Regulatory / mandated">
              <Toggle checked={assetForm.is_regulatory} onChange={({ detail }) => setAssetForm((f) => ({ ...f, is_regulatory: detail.checked }))}>Required by code</Toggle>
            </FormField>
          </ColumnLayout>
          <FormField label="Notes">
            <Textarea value={assetForm.notes} onChange={({ detail }) => setAssetForm((f) => ({ ...f, notes: detail.value }))} />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Service-log modal */}
      <Modal
        visible={logModalOpen}
        onDismiss={() => setLogModalOpen(false)}
        header={logTask ? `Log service — ${logTask.title}` : 'Log service'}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setLogModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingLog} onClick={saveLog}>Save</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <ColumnLayout columns={2}>
            <FormField label="Service date"><Input placeholder="YYYY-MM-DD" value={logForm.service_date} onChange={({ detail }) => setLogForm((f) => ({ ...f, service_date: detail.value }))} /></FormField>
            <FormField label="Performed by"><Input value={logForm.performed_by} onChange={({ detail }) => setLogForm((f) => ({ ...f, performed_by: detail.value }))} /></FormField>
            <FormField label="Vendor">{vendorSelect(logForm.vendor_id, (v) => setLogForm((f) => ({ ...f, vendor_id: v })))}</FormField>
            <FormField label="Cost"><Input type="number" value={logForm.cost} onChange={({ detail }) => setLogForm((f) => ({ ...f, cost: detail.value }))} /></FormField>
            <FormField label="Invoice #"><Input value={logForm.invoice_number} onChange={({ detail }) => setLogForm((f) => ({ ...f, invoice_number: detail.value }))} /></FormField>
          </ColumnLayout>
          <FormField label="Description" constraintText="Required">
            <Textarea value={logForm.description} onChange={({ detail }) => setLogForm((f) => ({ ...f, description: detail.value }))} />
          </FormField>
          {logHistory.length > 0 && (
            <Container header={<Header variant="h3">Service history</Header>}>
              <Table
                variant="embedded"
                items={logHistory}
                columnDefinitions={[
                  { id: 'date', header: 'Date', cell: (r) => fmtDate(r.service_date) },
                  { id: 'desc', header: 'Description', cell: (r) => r.description },
                  { id: 'by', header: 'By', cell: (r) => r.vendor?.company_name ?? r.performed_by ?? '—' },
                  { id: 'invoice', header: 'Invoice', cell: (r) => r.invoice_number ?? '—' },
                  { id: 'cost', header: 'Cost', cell: (r) => (r.cost != null ? `$${r.cost}` : '—') },
                ]}
              />
            </Container>
          )}
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default MaintenanceCategoryPanel;
