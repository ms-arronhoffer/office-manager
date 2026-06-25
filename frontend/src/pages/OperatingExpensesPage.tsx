import React, { useEffect, useState, useCallback } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Textarea from '@cloudscape-design/components/textarea';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { operatingExpenses as opexApi, leases as leasesApi } from '@/api';
import type { OperatingExpense, OperatingExpenseVariance } from '@/types';

const CATEGORIES = ['cam', 'insurance', 'taxes', 'utilities', 'other'];

const fmt = (v: number | null | undefined) =>
  v != null ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '—';

const varianceBadge = (v: number | null) => {
  if (v == null) return <Box color="text-body-secondary">—</Box>;
  const color = v > 0 ? 'red' : v < 0 ? 'green' : 'grey';
  return <Badge color={color}>{v > 0 ? '+' : ''}{fmt(v)}</Badge>;
};

interface LeaseOption { label: string; value: string; }

const OperatingExpensesPage: React.FC = () => {
  const { addFlashMessage } = useFlashbar();
  const [items, setItems] = useState<OperatingExpense[]>([]);
  const [variance, setVariance] = useState<OperatingExpenseVariance[]>([]);
  const [loading, setLoading] = useState(true);
  const [leaseOptions, setLeaseOptions] = useState<LeaseOption[]>([]);

  // Filters
  const [filterLeaseId, setFilterLeaseId] = useState<string>('');
  const [filterYear, setFilterYear] = useState<string>('');

  // Modal
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    lease_id: '', year: String(new Date().getFullYear()),
    category: 'cam', budgeted: '', actual: '', notes: '',
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {
        lease_id: filterLeaseId || undefined,
        year: filterYear ? parseInt(filterYear) : undefined,
      };
      const [itemsRes, varRes] = await Promise.all([
        opexApi.list(params),
        opexApi.variance(params),
      ]);
      setItems(itemsRes.data);
      setVariance(varRes.data);
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to load operating expenses.' });
    } finally {
      setLoading(false);
    }
  }, [filterLeaseId, filterYear, addFlashMessage]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    leasesApi.list({ page_size: 1000 }).then((res) => {
      setLeaseOptions(res.data.items.map((l) => ({ label: l.lease_name, value: l.id })));
    }).catch(() => {});
  }, []);

  const openCreate = () => {
    setEditingId(null);
    setForm({ lease_id: '', year: String(new Date().getFullYear()), category: 'cam', budgeted: '', actual: '', notes: '' });
    setModalOpen(true);
  };

  const openEdit = (e: OperatingExpense) => {
    setEditingId(e.id);
    setForm({
      lease_id: e.lease_id,
      year: String(e.year),
      category: e.category,
      budgeted: e.budgeted != null ? String(e.budgeted) : '',
      actual: e.actual != null ? String(e.actual) : '',
      notes: e.notes ?? '',
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!form.lease_id || !form.year || !form.category) return;
    setSaving(true);
    try {
      const payload = {
        lease_id: form.lease_id,
        year: parseInt(form.year),
        category: form.category,
        budgeted: form.budgeted ? parseFloat(form.budgeted) : undefined,
        actual: form.actual ? parseFloat(form.actual) : undefined,
        notes: form.notes || undefined,
      };
      if (editingId) {
        await opexApi.update(editingId, payload);
        addFlashMessage({ type: 'success', content: 'Expense updated.' });
      } else {
        await opexApi.create(payload);
        addFlashMessage({ type: 'success', content: 'Expense added.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to save expense.' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('Delete this expense record?')) return;
    try {
      await opexApi.delete(id);
      addFlashMessage({ type: 'success', content: 'Expense deleted.' });
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to delete expense.' });
    }
  };

  const totalBudgeted = items.reduce((s, i) => s + (i.budgeted ? Number(i.budgeted) : 0), 0);
  const totalActual = items.reduce((s, i) => s + (i.actual ? Number(i.actual) : 0), 0);
  const totalVariance = totalActual - totalBudgeted;

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Track CAM, insurance, taxes, and other operating expenses per lease year."
          actions={<Button variant="primary" onClick={openCreate}>Add expense</Button>}
        >
          Operating Expenses
        </Header>
      }
    >
      <SpaceBetween size="l">
        {/* ── Summary KPIs ── */}
        <Container header={<Header variant="h2">Summary</Header>}>
          <ColumnLayout columns={3} borders="vertical">
            <Box textAlign="center">
              <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">TOTAL BUDGETED</Box>
              <Box fontSize="heading-xl">{fmt(totalBudgeted)}</Box>
            </Box>
            <Box textAlign="center">
              <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">TOTAL ACTUAL</Box>
              <Box fontSize="heading-xl">{fmt(totalActual)}</Box>
            </Box>
            <Box textAlign="center">
              <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">VARIANCE</Box>
              <Box fontSize="heading-xl">{varianceBadge(totalVariance)}</Box>
            </Box>
          </ColumnLayout>
        </Container>

        {/* ── Filters ── */}
        <Container>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Lease">
              <Select
                selectedOption={leaseOptions.find((o) => o.value === filterLeaseId) ?? null}
                onChange={({ detail }) => setFilterLeaseId(detail.selectedOption?.value ?? '')}
                options={[{ label: 'All leases', value: '' }, ...leaseOptions]}
                placeholder="Filter by lease"
                filteringType="auto"
              />
            </FormField>
            <FormField label="Year">
              <Input
                value={filterYear}
                onChange={({ detail }) => setFilterYear(detail.value)}
                placeholder="e.g., 2025"
                type="number"
              />
            </FormField>
          </SpaceBetween>
        </Container>

        {/* ── Expense Table ── */}
        <Table
          loading={loading}
          items={items}
          columnDefinitions={[
            {
              id: 'year',
              header: 'Year',
              cell: (e: OperatingExpense) => e.year,
              width: 80,
            },
            {
              id: 'category',
              header: 'Category',
              cell: (e: OperatingExpense) => (
                <Badge color="blue">{e.category.toUpperCase()}</Badge>
              ),
            },
            {
              id: 'budgeted',
              header: 'Budgeted',
              cell: (e: OperatingExpense) => fmt(e.budgeted),
            },
            {
              id: 'actual',
              header: 'Actual',
              cell: (e: OperatingExpense) => fmt(e.actual),
            },
            {
              id: 'variance',
              header: 'Variance',
              cell: (e: OperatingExpense) =>
                varianceBadge(
                  e.actual != null && e.budgeted != null
                    ? Number(e.actual) - Number(e.budgeted)
                    : null
                ),
            },
            {
              id: 'reconciled',
              header: 'Reconciled',
              cell: (e: OperatingExpense) =>
                e.reconciled_at
                  ? <Badge color="green">Yes</Badge>
                  : <Badge color="grey">No</Badge>,
              width: 110,
            },
            {
              id: 'actions',
              header: '',
              cell: (e: OperatingExpense) => (
                <SpaceBetween direction="horizontal" size="xs">
                  <Button variant="inline-link" onClick={() => openEdit(e)}>Edit</Button>
                  <Button variant="inline-link" onClick={() => handleDelete(e.id)}>Delete</Button>
                </SpaceBetween>
              ),
              width: 120,
            },
          ]}
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <b>No operating expenses</b>
              <Box padding={{ bottom: 's' }} color="text-body-secondary">
                Add expense records to track CAM reconciliation.
              </Box>
            </Box>
          }
          header={<Header counter={`(${items.length})`}>Expense Records</Header>}
        />

        {/* ── Variance Summary ── */}
        {variance.length > 0 && (
          <Table
            items={variance}
            columnDefinitions={[
              { id: 'year', header: 'Year', cell: (r: OperatingExpenseVariance) => r.year, width: 80 },
              {
                id: 'category',
                header: 'Category',
                cell: (r: OperatingExpenseVariance) => <Badge color="blue">{r.category.toUpperCase()}</Badge>,
              },
              { id: 'budgeted', header: 'Budgeted', cell: (r: OperatingExpenseVariance) => fmt(r.budgeted) },
              { id: 'actual', header: 'Actual', cell: (r: OperatingExpenseVariance) => fmt(r.actual) },
              { id: 'variance', header: 'Variance', cell: (r: OperatingExpenseVariance) => varianceBadge(r.variance) },
            ]}
            header={<Header>Budget vs. Actual Variance</Header>}
          />
        )}
      </SpaceBetween>

      {/* ── Create / Edit Modal ── */}
      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editingId ? 'Edit expense' : 'Add operating expense'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button
                variant="primary"
                loading={saving}
                onClick={handleSave}
                disabled={!form.lease_id || !form.year || !form.category}
              >
                {editingId ? 'Save changes' : 'Add expense'}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Lease" description="Required">
            <Select
              selectedOption={leaseOptions.find((o) => o.value === form.lease_id) ?? null}
              onChange={({ detail }) => setForm((f) => ({ ...f, lease_id: detail.selectedOption?.value ?? '' }))}
              options={leaseOptions}
              placeholder="Select a lease"
              filteringType="auto"
            />
          </FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Year">
              <Input
                value={form.year}
                onChange={({ detail }) => setForm((f) => ({ ...f, year: detail.value }))}
                type="number"
                placeholder="2025"
              />
            </FormField>
            <FormField label="Category">
              <Select
                selectedOption={{ label: form.category.toUpperCase(), value: form.category }}
                onChange={({ detail }) => setForm((f) => ({ ...f, category: detail.selectedOption?.value ?? 'cam' }))}
                options={CATEGORIES.map((c) => ({ label: c.toUpperCase(), value: c }))}
              />
            </FormField>
          </SpaceBetween>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Budgeted ($)">
              <Input
                value={form.budgeted}
                onChange={({ detail }) => setForm((f) => ({ ...f, budgeted: detail.value }))}
                type="number"
                placeholder="e.g., 12000"
              />
            </FormField>
            <FormField label="Actual ($)">
              <Input
                value={form.actual}
                onChange={({ detail }) => setForm((f) => ({ ...f, actual: detail.value }))}
                type="number"
                placeholder="e.g., 13200"
              />
            </FormField>
          </SpaceBetween>
          <FormField label="Notes">
            <Textarea
              value={form.notes}
              onChange={({ detail }) => setForm((f) => ({ ...f, notes: detail.value }))}
              placeholder="Reconciliation notes..."
              rows={3}
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default OperatingExpensesPage;
