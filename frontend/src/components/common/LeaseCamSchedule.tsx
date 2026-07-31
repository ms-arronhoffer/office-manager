import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Table from '@cloudscape-design/components/table';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Textarea from '@cloudscape-design/components/textarea';
import Spinner from '@cloudscape-design/components/spinner';
import Badge from '@cloudscape-design/components/badge';
import Alert from '@cloudscape-design/components/alert';
import FileUpload from '@cloudscape-design/components/file-upload';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import Checkbox from '@cloudscape-design/components/checkbox';
import { leases as leasesApi, gl as glApi, ai as aiApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type {
  LeaseCamEntry,
  LeaseCamEntryInput,
  GLAccountOption,
  CamPeriodStatus,
  CamHistoryRow,
  CamHistoryParseResult,
} from '@/types';
import CamHistoryReviewModal from './CamHistoryReviewModal';

interface Props {
  leaseId: string;
  canEdit: boolean;
}

type ChargeType = 'fixed' | 'percent_increase';

interface CamFormState {
  year: string;
  charge_type: ChargeType;
  amount: string;
  percent_increase: string;
  gl_account_id: string;
  notes: string;
  period_status: CamPeriodStatus;
  period_start: string;
  period_end: string;
  base_rent_amount: string;
  base_rent_frequency: 'monthly' | 'quarterly' | 'annually' | '';
  base_rent_escalation_rate: string;
  operating_expense_amount: string;
  cam_psf: string;
  reconciliation_true_up: string;
}

const emptyForm = (): CamFormState => ({
  year: String(new Date().getFullYear()),
  charge_type: 'fixed',
  amount: '',
  percent_increase: '',
  gl_account_id: '',
  notes: '',
  period_status: 'current',
  period_start: '',
  period_end: '',
  base_rent_amount: '',
  base_rent_frequency: '',
  base_rent_escalation_rate: '',
  operating_expense_amount: '',
  cam_psf: '',
  reconciliation_true_up: '',
});

const CHARGE_TYPE_OPTIONS = [
  { value: 'fixed', label: 'Fixed amount' },
  { value: 'percent_increase', label: 'Percent increase (over prior year)' },
];

const PERIOD_STATUS_OPTIONS = [
  { value: 'current', label: 'Current' },
  { value: 'historical', label: 'Historical' },
  { value: 'projected', label: 'Projected' },
];

const FREQUENCY_OPTIONS = [
  { value: '', label: '— None —' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'quarterly', label: 'Quarterly' },
  { value: 'annually', label: 'Annually' },
];

const formatAmount = (v: number | null | undefined): string =>
  v != null ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

const formatPercent = (v: number | null | undefined): string =>
  v != null ? `${(Number(v) * 100).toLocaleString(undefined, { maximumFractionDigits: 4 })}%` : '—';

const SOURCE_LABELS: Record<string, string> = {
  manual: 'Manual',
  ai_import: 'AI import',
  csv_import: 'CSV import',
  reconciliation: 'Reconciliation',
};

function ConfidenceBadge({ value }: { value: number | null }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  if (value >= 0.8) return <Badge color="green">{pct}%</Badge>;
  if (value >= 0.5) return <Badge color="blue">{pct}%</Badge>;
  return <Badge color="grey">{pct}%</Badge>;
}

function periodStatusBadge(status: string | undefined): React.ReactNode {
  if (status === 'historical') return <Badge color="grey">Historical</Badge>;
  if (status === 'projected') return <Badge color="blue">Projected</Badge>;
  if (status === 'current') return <Badge color="green">Current</Badge>;
  return null;
}

/** Group entries by period_status */
function groupEntries(entries: LeaseCamEntry[]) {
  const historical: LeaseCamEntry[] = [];
  const current: LeaseCamEntry[] = [];
  const projected: LeaseCamEntry[] = [];
  for (const e of entries) {
    if (e.period_status === 'historical') historical.push(e);
    else if (e.period_status === 'projected') projected.push(e);
    else current.push(e);
  }
  return { historical, current, projected };
}

/** Simple YoY trend table */
function TrendTable({ entries }: { entries: LeaseCamEntry[] }) {
  const sorted = [...entries].sort((a, b) => a.year - b.year);
  const rows = sorted.map((e, i) => {
    const prev = sorted[i - 1];
    const currAmt = e.effective_amount ?? e.amount;
    const prevAmt = prev ? (prev.effective_amount ?? prev.amount) : null;
    const rentDelta =
      e.base_rent_amount != null && prev?.base_rent_amount != null
        ? e.base_rent_amount - prev.base_rent_amount
        : null;
    const camDelta =
      currAmt != null && prevAmt != null ? currAmt - prevAmt : null;
    return { year: e.year, base_rent: e.base_rent_amount, eff_cam: currAmt, rentDelta, camDelta };
  });

  if (rows.length < 2) return null;

  return (
    <Box>
      <Box variant="h4" margin={{ bottom: 'xs' }}>Year-over-year trend</Box>
      <Table
        variant="embedded"
        items={rows}
        columnDefinitions={[
          { id: 'year', header: 'Year', cell: (r) => r.year, width: 80 },
          { id: 'base_rent', header: 'Base Rent', cell: (r) => formatAmount(r.base_rent ?? null), width: 120 },
          {
            id: 'rent_delta',
            header: 'Rent Δ',
            cell: (r) =>
              r.rentDelta != null ? (
                <Box color={r.rentDelta >= 0 ? 'text-status-success' : 'text-status-error'}>
                  {r.rentDelta >= 0 ? '+' : ''}{formatAmount(r.rentDelta)}
                </Box>
              ) : '—',
            width: 100,
          },
          { id: 'eff_cam', header: 'Eff. CAM', cell: (r) => formatAmount(r.eff_cam ?? null), width: 120 },
          {
            id: 'cam_delta',
            header: 'CAM Δ',
            cell: (r) =>
              r.camDelta != null ? (
                <Box color={r.camDelta >= 0 ? 'text-status-success' : 'text-status-error'}>
                  {r.camDelta >= 0 ? '+' : ''}{formatAmount(r.camDelta)}
                </Box>
              ) : '—',
            width: 100,
          },
        ]}
      />
    </Box>
  );
}

const LeaseCamSchedule: React.FC<Props> = ({ leaseId, canEdit }) => {
  const { addFlash } = useFlashbar();
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [entries, setEntries] = useState<LeaseCamEntry[]>([]);
  const [glAccounts, setGlAccounts] = useState<GLAccountOption[]>([]);

  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<CamFormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Promote confirmation
  const [promoteTarget, setPromoteTarget] = useState<LeaseCamEntry | null>(null);
  const [promoting, setPromoting] = useState(false);

  // Import history flow
  const [importChooserVisible, setImportChooserVisible] = useState(false);
  const [importMode, setImportMode] = useState<'ai' | 'csv'>('ai');
  const [importFile, setImportFile] = useState<File[]>([]);
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // CAM history review modal
  const [reviewVisible, setReviewVisible] = useState(false);
  const [reviewRows, setReviewRows] = useState<CamHistoryRow[]>([]);
  const [reviewMeta, setReviewMeta] = useState<CamHistoryParseResult | null>(null);

  const glOptions = useMemo(
    () => [
      { label: '— None —', value: '' },
      ...glAccounts.map((a) => ({ label: `${a.code} — ${a.name}`, value: String(a.id) })),
    ],
    [glAccounts],
  );

  const fetchEntries = useCallback(async () => {
    if (!leaseId) return;
    setLoading(true);
    try {
      const res = await leasesApi.listCamEntries(leaseId);
      setEntries(res.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load CAM schedule.' });
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, [leaseId, addFlash]);

  useEffect(() => {
    glApi
      .accountOptions()
      .then((res) => setGlAccounts(res.data))
      .catch(() => {});
  }, []);

  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm());
    setModalVisible(true);
  };

  const openEdit = (entry: LeaseCamEntry) => {
    setEditingId(entry.id);
    setForm({
      year: String(entry.year),
      charge_type: (entry.charge_type === 'percent_increase' ? 'percent_increase' : 'fixed') as ChargeType,
      amount: entry.amount != null ? String(entry.amount) : '',
      percent_increase: entry.percent_increase != null ? String(entry.percent_increase * 100) : '',
      gl_account_id: entry.gl_account_id ?? '',
      notes: entry.notes ?? '',
      period_status: (entry.period_status as CamPeriodStatus) || 'current',
      period_start: entry.period_start ?? '',
      period_end: entry.period_end ?? '',
      base_rent_amount: entry.base_rent_amount != null ? String(entry.base_rent_amount) : '',
      base_rent_frequency: (entry.base_rent_frequency as '' | 'monthly' | 'quarterly' | 'annually') ?? '',
      base_rent_escalation_rate:
        entry.base_rent_escalation_rate != null
          ? String(Number(entry.base_rent_escalation_rate) * 100)
          : '',
      operating_expense_amount:
        entry.operating_expense_amount != null ? String(entry.operating_expense_amount) : '',
      cam_psf: entry.cam_psf != null ? String(entry.cam_psf) : '',
      reconciliation_true_up: entry.reconciliation_true_up != null ? String(entry.reconciliation_true_up) : '',
    });
    setModalVisible(true);
  };

  const buildPayload = (): LeaseCamEntryInput => {
    const payload: LeaseCamEntryInput = {
      year: parseInt(form.year, 10),
      charge_type: form.charge_type,
      gl_account_id: form.gl_account_id || null,
      notes: form.notes.trim() || null,
      period_status: form.period_status || 'current',
      period_start: form.period_start || null,
      period_end: form.period_end || null,
      base_rent_amount: form.base_rent_amount ? form.base_rent_amount : null,
      base_rent_frequency: (form.base_rent_frequency as 'monthly' | 'quarterly' | 'annually') || null,
      base_rent_escalation_rate: form.base_rent_escalation_rate
        ? String(parseFloat(form.base_rent_escalation_rate) / 100)
        : null,
      operating_expense_amount: form.operating_expense_amount || null,
      cam_psf: form.cam_psf || null,
      reconciliation_true_up: form.reconciliation_true_up || null,
    };
    if (form.charge_type === 'fixed') {
      payload.amount = form.amount.trim() ? form.amount.trim() : null;
      payload.percent_increase = null;
    } else {
      const pct = form.percent_increase.trim();
      payload.percent_increase = pct ? String(parseFloat(pct) / 100) : null;
      payload.amount = null;
    }
    return payload;
  };

  const handleSave = async () => {
    if (!form.year.trim() || Number.isNaN(parseInt(form.year, 10))) {
      addFlash({ type: 'error', content: 'A valid year is required.' });
      return;
    }
    setSaving(true);
    try {
      const payload = buildPayload();
      if (editingId) {
        await leasesApi.updateCamEntry(leaseId, editingId, payload);
        addFlash({ type: 'success', content: 'CAM entry updated.' });
      } else {
        await leasesApi.createCamEntry(leaseId, payload);
        addFlash({ type: 'success', content: 'CAM entry added.' });
      }
      setModalVisible(false);
      await fetchEntries();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save CAM entry.' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (entry: LeaseCamEntry) => {
    setDeletingId(entry.id);
    try {
      await leasesApi.deleteCamEntry(leaseId, entry.id);
      await fetchEntries();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete CAM entry.' });
    } finally {
      setDeletingId(null);
    }
  };

  const handlePromote = async () => {
    if (!promoteTarget) return;
    setPromoting(true);
    try {
      await leasesApi.promoteCamEntry(leaseId, promoteTarget.id);
      addFlash({
        type: 'success',
        content: `Year ${promoteTarget.year} values promoted to current lease terms.`,
      });
      setPromoteTarget(null);
      await fetchEntries();
    } catch {
      addFlash({ type: 'error', content: 'Failed to promote entry to current terms.' });
    } finally {
      setPromoting(false);
    }
  };

  const handleRunImport = async () => {
    if (importFile.length === 0) return;
    setImportLoading(true);
    setImportError(null);
    try {
      let result: CamHistoryParseResult;
      if (importMode === 'ai') {
        const res = await aiApi.parseLeaseHistory(importFile[0]);
        result = res.data;
      } else {
        const res = await leasesApi.parseCamHistoryCsv(leaseId, importFile[0]);
        result = res.data;
      }
      setReviewRows(result.periods);
      setReviewMeta(result);
      setImportChooserVisible(false);
      setReviewVisible(true);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setImportError(detail || 'Failed to parse file.');
    } finally {
      setImportLoading(false);
    }
  };

  const sortedEntries = useMemo(() => [...entries].sort((a, b) => a.year - b.year), [entries]);
  const { historical, current, projected } = useMemo(() => groupEntries(sortedEntries), [sortedEntries]);

  const columnDefs = (section: CamPeriodStatus) => [
    { id: 'year', header: 'Year', cell: (e: LeaseCamEntry) => e.year, width: 70 },
    {
      id: 'period_status',
      header: 'Status',
      cell: (e: LeaseCamEntry) => periodStatusBadge(e.period_status),
      width: 110,
    },
    {
      id: 'source',
      header: 'Source',
      cell: (e: LeaseCamEntry) => SOURCE_LABELS[e.source] || e.source || '—',
      width: 100,
    },
    {
      id: 'period',
      header: 'Period',
      cell: (e: LeaseCamEntry) =>
        e.period_start || e.period_end
          ? `${e.period_start || ''}${e.period_start && e.period_end ? ' – ' : ''}${e.period_end || ''}`
          : '—',
      width: 160,
    },
    {
      id: 'base_rent',
      header: 'Base Rent',
      cell: (e: LeaseCamEntry) =>
        e.base_rent_amount != null
          ? `${formatAmount(e.base_rent_amount)}${e.base_rent_frequency ? ` / ${e.base_rent_frequency}` : ''}`
          : '—',
      width: 150,
    },
    {
      id: 'effective_cam',
      header: 'Eff. CAM',
      cell: (e: LeaseCamEntry) => formatAmount(e.effective_amount ?? e.amount),
      width: 110,
    },
    {
      id: 'charge_type',
      header: 'Charge Type',
      cell: (e: LeaseCamEntry) =>
        e.charge_type === 'percent_increase' ? 'Pct increase' : 'Fixed',
      width: 100,
    },
    {
      id: 'value',
      header: 'Amount / %',
      cell: (e: LeaseCamEntry) =>
        e.charge_type === 'percent_increase'
          ? formatPercent(e.percent_increase)
          : formatAmount(e.amount),
      width: 110,
    },
    {
      id: 'true_up',
      header: 'True-up',
      cell: (e: LeaseCamEntry) => formatAmount(e.reconciliation_true_up),
      width: 100,
    },
    {
      id: 'confidence',
      header: 'Confidence',
      cell: (e: LeaseCamEntry) => <ConfidenceBadge value={e.extraction_confidence} />,
      width: 90,
    },
    {
      id: 'source_doc',
      header: 'Source doc',
      cell: (e: LeaseCamEntry) => (e.source_document_id ? '📎' : '—'),
      width: 80,
    },
    { id: 'notes', header: 'Notes', cell: (e: LeaseCamEntry) => e.notes || '—', width: 140 },
    ...(canEdit
      ? [
          {
            id: 'actions',
            header: 'Actions',
            cell: (e: LeaseCamEntry) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => openEdit(e)}>Edit</Button>
                {section !== 'historical' && (
                  <Button variant="inline-link" onClick={() => setPromoteTarget(e)}>
                    Promote
                  </Button>
                )}
                <Button
                  variant="inline-link"
                  loading={deletingId === e.id}
                  onClick={() => handleDelete(e)}
                >
                  Delete
                </Button>
              </SpaceBetween>
            ),
            width: 200,
          },
        ]
      : []),
  ];

  return (
    <>
      {/* Manual add/edit modal */}
      <Modal
        visible={modalVisible}
        onDismiss={() => setModalVisible(false)}
        header={editingId ? 'Edit CAM Entry' : 'Add CAM Entry'}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setModalVisible(false)}>Cancel</Button>
              <Button variant="primary" loading={saving} onClick={handleSave}>
                {editingId ? 'Save' : 'Add'}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Year">
              <Input
                type="number"
                value={form.year}
                onChange={({ detail }) => setForm((p) => ({ ...p, year: detail.value }))}
                placeholder="e.g., 2020"
              />
            </FormField>
            <FormField label="Period Status">
              <Select
                selectedOption={
                  PERIOD_STATUS_OPTIONS.find((o) => o.value === form.period_status) ??
                  PERIOD_STATUS_OPTIONS[0]
                }
                onChange={({ detail }) =>
                  setForm((p) => ({
                    ...p,
                    period_status: (detail.selectedOption.value as CamPeriodStatus) ?? 'current',
                  }))
                }
                options={PERIOD_STATUS_OPTIONS}
              />
            </FormField>
          </SpaceBetween>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Period Start">
              <Input
                value={form.period_start}
                placeholder="YYYY-MM-DD"
                onChange={({ detail }) => setForm((p) => ({ ...p, period_start: detail.value }))}
              />
            </FormField>
            <FormField label="Period End">
              <Input
                value={form.period_end}
                placeholder="YYYY-MM-DD"
                onChange={({ detail }) => setForm((p) => ({ ...p, period_end: detail.value }))}
              />
            </FormField>
          </SpaceBetween>
          <FormField label="Charge Type">
            <Select
              selectedOption={
                CHARGE_TYPE_OPTIONS.find((o) => o.value === form.charge_type) ??
                CHARGE_TYPE_OPTIONS[0]
              }
              onChange={({ detail }) =>
                setForm((p) => ({
                  ...p,
                  charge_type: (detail.selectedOption.value as ChargeType) ?? 'fixed',
                }))
              }
              options={CHARGE_TYPE_OPTIONS}
            />
          </FormField>
          {form.charge_type === 'fixed' ? (
            <FormField label="CAM Amount" description="Fixed CAM charge for the year.">
              <Input
                type="number"
                value={form.amount}
                onChange={({ detail }) => setForm((p) => ({ ...p, amount: detail.value }))}
                placeholder="e.g., 12000.00"
              />
            </FormField>
          ) : (
            <FormField
              label="Percent Increase"
              description="Percent increase over the prior year's CAM (e.g., 3 for 3%)."
            >
              <Input
                type="number"
                value={form.percent_increase}
                onChange={({ detail }) => setForm((p) => ({ ...p, percent_increase: detail.value }))}
                placeholder="e.g., 3"
              />
            </FormField>
          )}
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Base Rent" description="Annual/monthly base rent for this year.">
              <Input
                type="number"
                value={form.base_rent_amount}
                onChange={({ detail }) => setForm((p) => ({ ...p, base_rent_amount: detail.value }))}
                placeholder="e.g., 60000.00"
              />
            </FormField>
            <FormField label="Frequency">
              <Select
                selectedOption={
                  FREQUENCY_OPTIONS.find((o) => o.value === form.base_rent_frequency) ??
                  FREQUENCY_OPTIONS[0]
                }
                onChange={({ detail }) =>
                  setForm((p) => ({
                    ...p,
                    base_rent_frequency:
                      (detail.selectedOption.value as '' | 'monthly' | 'quarterly' | 'annually') ??
                      '',
                  }))
                }
                options={FREQUENCY_OPTIONS}
              />
            </FormField>
          </SpaceBetween>
          <FormField
            label="Base Rent Escalation Rate (%)"
            description="Annual escalation percent (e.g. 3 for 3%)."
          >
            <Input
              type="number"
              value={form.base_rent_escalation_rate}
              onChange={({ detail }) =>
                setForm((p) => ({ ...p, base_rent_escalation_rate: detail.value }))
              }
              placeholder="e.g., 3"
            />
          </FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Operating Expenses">
              <Input
                type="number"
                value={form.operating_expense_amount}
                onChange={({ detail }) =>
                  setForm((p) => ({ ...p, operating_expense_amount: detail.value }))
                }
                placeholder="e.g., 8000.00"
              />
            </FormField>
            <FormField label="CAM PSF">
              <Input
                type="number"
                value={form.cam_psf}
                onChange={({ detail }) => setForm((p) => ({ ...p, cam_psf: detail.value }))}
                placeholder="e.g., 4.50"
              />
            </FormField>
            <FormField label="Reconciliation True-up">
              <Input
                type="number"
                value={form.reconciliation_true_up}
                onChange={({ detail }) =>
                  setForm((p) => ({ ...p, reconciliation_true_up: detail.value }))
                }
                placeholder="e.g., -500.00"
              />
            </FormField>
          </SpaceBetween>
          <FormField label="GL Account" description="Optional general-ledger account.">
            <Select
              selectedOption={
                glOptions.find((o) => o.value === form.gl_account_id) ?? glOptions[0]
              }
              onChange={({ detail }) =>
                setForm((p) => ({ ...p, gl_account_id: detail.selectedOption.value ?? '' }))
              }
              options={glOptions}
              filteringType="auto"
              empty="No GL accounts available"
            />
          </FormField>
          <FormField label="Notes">
            <Textarea
              value={form.notes}
              onChange={({ detail }) => setForm((p) => ({ ...p, notes: detail.value }))}
              placeholder="Optional notes"
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Promote confirmation modal */}
      <Modal
        visible={promoteTarget != null}
        onDismiss={() => setPromoteTarget(null)}
        header="Promote to current terms?"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setPromoteTarget(null)}>Cancel</Button>
              <Button variant="primary" loading={promoting} onClick={handlePromote}>
                Promote
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Alert type="warning">
          This will <strong>overwrite</strong> the lease's current financial terms (base rent,
          escalation rate, etc.) with the values from year {promoteTarget?.year}. This action cannot
          be undone automatically. Are you sure?
        </Alert>
      </Modal>

      {/* Import chooser modal */}
      <Modal
        visible={importChooserVisible}
        onDismiss={() => {
          setImportChooserVisible(false);
          setImportFile([]);
          setImportError(null);
        }}
        header="Import historical CAM data"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                onClick={() => {
                  setImportChooserVisible(false);
                  setImportFile([]);
                  setImportError(null);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={importLoading}
                disabled={importFile.length === 0}
                onClick={handleRunImport}
              >
                Parse file
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Alert type="info">
            Upload a document to extract historical CAM rows. You will be able to review and edit
            the rows before they are saved. Importing history <strong>does not change</strong> the
            lease's current financial terms.
          </Alert>
          <FormField label="Source">
            <Select
              selectedOption={
                importMode === 'ai'
                  ? { value: 'ai', label: 'AI — PDF / image / text' }
                  : { value: 'csv', label: 'CSV file' }
              }
              onChange={({ detail }) =>
                setImportMode((detail.selectedOption.value as 'ai' | 'csv') ?? 'ai')
              }
              options={[
                { value: 'ai', label: 'AI — PDF / image / text' },
                { value: 'csv', label: 'CSV file' },
              ]}
            />
          </FormField>
          <FileUpload
            onChange={({ detail }) => setImportFile(detail.value)}
            value={importFile}
            accept={importMode === 'csv' ? '.csv' : '.pdf,.txt,.docx,.png,.jpg,.jpeg,.tif,.tiff'}
            i18nStrings={{
              uploadButtonText: () => 'Choose file',
              dropzoneText: () => 'Drop file here',
              removeFileAriaLabel: (i) => `Remove file ${i + 1}`,
              limitShowFewer: 'Show fewer',
              limitShowMore: 'Show more',
              errorIconAriaLabel: 'Error',
            }}
            constraintText={importMode === 'csv' ? 'CSV, max 2 MB' : 'PDF, image, or text document'}
          />
          {importError && <Alert type="error">{importError}</Alert>}
        </SpaceBetween>
      </Modal>

      {/* History review modal */}
      <CamHistoryReviewModal
        visible={reviewVisible}
        rows={reviewRows}
        warnings={reviewMeta?.warnings}
        leaseId={leaseId}
        defaultPeriodStatus="historical"
        source={importMode === 'ai' ? 'ai_import' : 'csv_import'}
        onDismiss={() => setReviewVisible(false)}
        onConfirm={(_rows, _opts, importResult) => {
          setReviewVisible(false);
          if (importResult) {
            const { created, updated, skipped, conflicts } = importResult;
            addFlash({
              type: conflicts > 0 ? 'warning' : 'success',
              content: `Import complete — created: ${created}, updated: ${updated}, skipped: ${skipped}, conflicts: ${conflicts}.`,
            });
            fetchEntries();
          }
        }}
      />

      <ExpandableSection
        headerText={`CAM Schedule${entries.length > 0 ? ` (${entries.length})` : ''}`}
        expanded={expanded}
        onChange={({ detail }) => {
          setExpanded(detail.expanded);
          if (detail.expanded && !loaded && !loading) {
            fetchEntries();
          }
        }}
        variant="container"
      >
        {loading ? (
          <Box textAlign="center" padding="l">
            <Spinner size="normal" />
          </Box>
        ) : (
          <SpaceBetween size="l">
            {canEdit && (
              <Box float="right">
                <SpaceBetween direction="horizontal" size="xs">
                  <Button onClick={() => setImportChooserVisible(true)}>Import history</Button>
                  <Button variant="primary" onClick={openCreate}>
                    Add CAM Entry
                  </Button>
                </SpaceBetween>
              </Box>
            )}

            {/* Current section */}
            {(current.length > 0 || entries.length === 0) && (
              <Container header={<Header variant="h3">Current schedule</Header>}>
                <Table
                  columnDefinitions={columnDefs('current')}
                  items={current}
                  empty={
                    <Box textAlign="center" color="inherit" padding="m">
                      No current CAM entries. Click "Add CAM Entry" to begin.
                    </Box>
                  }
                  stripedRows
                  variant="embedded"
                />
              </Container>
            )}

            {/* Historical section */}
            {historical.length > 0 && (
              <Container
                header={
                  <Header
                    variant="h3"
                    description="Historical reference data — imported for context only. These rows do not affect the active lease's financial terms."
                  >
                    Historical
                  </Header>
                }
              >
                <Table
                  columnDefinitions={columnDefs('historical')}
                  items={historical}
                  stripedRows
                  variant="embedded"
                />
              </Container>
            )}

            {/* Projected section */}
            {projected.length > 0 && (
              <Container header={<Header variant="h3">Projected</Header>}>
                <Table
                  columnDefinitions={columnDefs('projected')}
                  items={projected}
                  stripedRows
                  variant="embedded"
                />
              </Container>
            )}

            {/* Trend table */}
            {sortedEntries.length >= 2 && <TrendTable entries={sortedEntries} />}
          </SpaceBetween>
        )}
      </ExpandableSection>
    </>
  );
};

export default LeaseCamSchedule;

