import React, { useState, useMemo, useCallback } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Alert from '@cloudscape-design/components/alert';
import Select from '@cloudscape-design/components/select';
import Checkbox from '@cloudscape-design/components/checkbox';
import Badge from '@cloudscape-design/components/badge';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import { leases as leasesApi } from '@/api';
import type {
  CamHistoryRow,
  CamImportMode,
  CamPeriodStatus,
  CamImportResult,
} from '@/types';

interface ReviewRow extends CamHistoryRow {
  /** Client-side uid so table selection can key on it */
  _uid: string;
}

export interface CamHistoryConfirmOptions {
  mode: CamImportMode;
  period_status: CamPeriodStatus | 'auto';
  allow_active_period_overlap: boolean;
  source_document_id?: string | null;
}

interface Props {
  visible: boolean;
  rows: CamHistoryRow[];
  warnings?: string[];
  /** When set, the modal POSTs the import immediately after confirmation. */
  leaseId?: string;
  defaultPeriodStatus?: CamPeriodStatus | 'auto';
  source?: string;
  sourceDocumentId?: string | null;
  onDismiss: () => void;
  /**
   * Called when the user confirms.
   * - If `leaseId` is set and the import succeeded, `importResult` is provided.
   * - If `leaseId` is NOT set, the parent is responsible for importing later.
   */
  onConfirm: (
    rows: CamHistoryRow[],
    options: CamHistoryConfirmOptions,
    importResult?: CamImportResult,
  ) => void;
}

const MODE_OPTIONS = [
  { value: 'skip_existing', label: 'Skip existing years' },
  { value: 'overwrite', label: 'Overwrite existing years' },
  { value: 'append', label: 'Append alongside existing years' },
];

const PERIOD_STATUS_OPTIONS = [
  { value: 'auto', label: 'Auto (derive from year)' },
  { value: 'historical', label: 'Historical' },
  { value: 'current', label: 'Current' },
  { value: 'projected', label: 'Projected' },
];

const FREQUENCY_OPTIONS = [
  { value: '', label: '— None —' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'quarterly', label: 'Quarterly' },
  { value: 'annually', label: 'Annually' },
];

function confidenceBadge(conf: number | null | undefined): React.ReactNode {
  if (conf == null) return null;
  const pct = Math.round(conf * 100);
  if (conf >= 0.8) return <Badge color="green">{pct}%</Badge>;
  if (conf >= 0.5) return <Badge color="blue">{pct}%</Badge>;
  return <Badge color="grey">{pct}%</Badge>;
}

function fmt(v: number | null | undefined): string {
  if (v == null) return '';
  return String(v);
}

const CamHistoryReviewModal: React.FC<Props> = ({
  visible,
  rows,
  warnings,
  leaseId,
  defaultPeriodStatus = 'historical',
  source = 'ai_import',
  sourceDocumentId,
  onDismiss,
  onConfirm,
}) => {
  const initialRows: ReviewRow[] = useMemo(
    () => rows.map((r, i) => ({ ...r, _uid: `row-${i}-${r.year}` })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visible],
  );

  const [reviewRows, setReviewRows] = useState<ReviewRow[]>(initialRows);
  const [selectedItems, setSelectedItems] = useState<ReviewRow[]>(initialRows);
  const [mode, setMode] = useState<CamImportMode>('skip_existing');
  const [periodStatus, setPeriodStatus] = useState<CamPeriodStatus | 'auto'>(defaultPeriodStatus);
  const [allowOverlap, setAllowOverlap] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<CamImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [reverting, setReverting] = useState(false);

  // Sync rows when the modal reopens with new data
  React.useEffect(() => {
    if (visible) {
      const fresh = rows.map((r, i) => ({ ...r, _uid: `row-${i}-${r.year}` }));
      setReviewRows(fresh);
      setSelectedItems(fresh);
      setMode('skip_existing');
      setPeriodStatus(defaultPeriodStatus);
      setAllowOverlap(false);
      setImportResult(null);
      setImportError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const updateRow = useCallback((uid: string, patch: Partial<ReviewRow>) => {
    setReviewRows((prev) => prev.map((r) => (r._uid === uid ? { ...r, ...patch } : r)));
    setSelectedItems((prev) => prev.map((r) => (r._uid === uid ? { ...r, ...patch } : r)));
  }, []);

  const selectedSet = useMemo(() => new Set(selectedItems.map((r) => r._uid)), [selectedItems]);

  const handleConfirm = async () => {
    const chosenRows = reviewRows.filter((r) => selectedSet.has(r._uid));
    const opts: CamHistoryConfirmOptions = {
      mode,
      period_status: periodStatus,
      allow_active_period_overlap: allowOverlap,
      source_document_id: sourceDocumentId,
    };

    if (!leaseId) {
      onConfirm(chosenRows, opts);
      return;
    }

    setImporting(true);
    setImportError(null);
    try {
      const res = await leasesApi.importCamHistory(leaseId, {
        rows: chosenRows,
        mode: opts.mode,
        period_status: opts.period_status,
        source: source as import('@/types').CamImportMode,
        source_document_id: opts.source_document_id ?? null,
        allow_active_period_overlap: opts.allow_active_period_overlap,
        apply_to_lease: false,
      });
      setImportResult(res.data);
      onConfirm(chosenRows, opts, res.data);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setImportError(detail || 'Failed to import history rows.');
    } finally {
      setImporting(false);
    }
  };

  const handleRevert = async () => {
    if (!leaseId || !importResult) return;
    setReverting(true);
    try {
      await leasesApi.revertCamHistoryImport(leaseId, importResult.import_batch_id);
      setImportResult(null);
      onDismiss();
    } catch {
      setImportError('Failed to revert import batch.');
    } finally {
      setReverting(false);
    }
  };

  const conflictRows = importResult
    ? importResult.results.filter((r) => r.status === 'conflict')
    : [];

  const statusColMap: Record<string, string> = {};
  if (importResult) {
    for (const r of importResult.results) {
      statusColMap[String(r.year)] = r.status + (r.reason ? ` — ${r.reason}` : '');
    }
  }

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      size="max"
      header="Review historical CAM rows"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={onDismiss} disabled={importing || reverting}>
              Cancel
            </Button>
            {importResult && conflictRows.length > 0 && (
              <Button
                variant="normal"
                loading={reverting}
                onClick={handleRevert}
              >
                Revert import
              </Button>
            )}
            {!importResult && (
              <Button
                variant="primary"
                loading={importing}
                disabled={selectedItems.length === 0}
                onClick={handleConfirm}
              >
                {leaseId ? 'Import selected rows' : 'Confirm selection'}
              </Button>
            )}
            {importResult && (
              <Button variant="primary" onClick={onDismiss}>
                Done
              </Button>
            )}
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Alert type="info">
          Importing historical rows <strong>does not change</strong> the lease's current financial
          terms (base rent, escalation rate, etc.). Those fields remain the active lease record's
          source of truth. Use "Promote to current terms" on an individual row only when you
          explicitly want to copy that row's values onto the live lease.
        </Alert>

        {warnings && warnings.length > 0 && (
          <Alert type="warning">
            {warnings.map((w, i) => (
              <div key={i}>{w}</div>
            ))}
          </Alert>
        )}

        {importError && <Alert type="error">{importError}</Alert>}

        {importResult && (
          <Alert type={conflictRows.length > 0 ? 'warning' : 'success'}>
            Import complete — created: {importResult.created}, updated: {importResult.updated},
            skipped: {importResult.skipped}, conflicts: {importResult.conflicts}.
            {conflictRows.length > 0 && (
              <>
                {' '}
                Conflicting years:{' '}
                {conflictRows.map((r) => `${r.year}${r.reason ? ` (${r.reason})` : ''}`).join(', ')}
              </>
            )}
          </Alert>
        )}

        {/* Import options */}
        {!importResult && (
          <SpaceBetween size="s">
            <SpaceBetween direction="horizontal" size="m">
              <FormField label="Conflict mode">
                <Select
                  selectedOption={MODE_OPTIONS.find((o) => o.value === mode) ?? MODE_OPTIONS[0]}
                  onChange={({ detail }) => setMode((detail.selectedOption.value as CamImportMode) ?? 'skip_existing')}
                  options={MODE_OPTIONS}
                />
              </FormField>
              <FormField label="Period status">
                <Select
                  selectedOption={PERIOD_STATUS_OPTIONS.find((o) => o.value === periodStatus) ?? PERIOD_STATUS_OPTIONS[0]}
                  onChange={({ detail }) => setPeriodStatus((detail.selectedOption.value as CamPeriodStatus | 'auto') ?? 'auto')}
                  options={PERIOD_STATUS_OPTIONS}
                />
              </FormField>
            </SpaceBetween>
            <Checkbox
              checked={allowOverlap}
              onChange={({ detail }) => setAllowOverlap(detail.checked)}
            >
              Allow overlap with active lease term (historical rows that fall within the active
              lease period will otherwise be flagged as conflicts)
            </Checkbox>
          </SpaceBetween>
        )}

        <Table<ReviewRow>
          selectionType={importResult ? undefined : 'multi'}
          selectedItems={importResult ? undefined : selectedItems}
          onSelectionChange={({ detail }) => setSelectedItems(detail.selectedItems)}
          trackBy="_uid"
          items={reviewRows}
          columnDefinitions={[
            {
              id: 'year',
              header: 'Year',
              cell: (r) =>
                importResult ? (
                  <span>{r.year}</span>
                ) : (
                  <Input
                    type="number"
                    value={String(r.year)}
                    onChange={({ detail }) =>
                      updateRow(r._uid, { year: parseInt(detail.value, 10) || r.year })
                    }
                  />
                ),
              width: 90,
            },
            {
              id: 'period',
              header: 'Period',
              cell: (r) =>
                importResult ? (
                  <span>
                    {r.period_start || ''}
                    {r.period_start && r.period_end ? ' – ' : ''}
                    {r.period_end || ''}
                  </span>
                ) : (
                  <SpaceBetween direction="horizontal" size="xxs">
                    <Input
                      value={r.period_start ?? ''}
                      placeholder="YYYY-MM-DD"
                      onChange={({ detail }) => updateRow(r._uid, { period_start: detail.value || null })}
                    />
                    <Input
                      value={r.period_end ?? ''}
                      placeholder="YYYY-MM-DD"
                      onChange={({ detail }) => updateRow(r._uid, { period_end: detail.value || null })}
                    />
                  </SpaceBetween>
                ),
              width: 220,
            },
            {
              id: 'base_rent',
              header: 'Base Rent',
              cell: (r) =>
                importResult ? (
                  <span>
                    {r.base_rent_amount != null ? `$${Number(r.base_rent_amount).toLocaleString()}` : '—'}
                  </span>
                ) : (
                  <SpaceBetween direction="horizontal" size="xxs">
                    <Input
                      type="number"
                      value={fmt(r.base_rent_amount)}
                      placeholder="Amount"
                      onChange={({ detail }) =>
                        updateRow(r._uid, {
                          base_rent_amount: detail.value ? parseFloat(detail.value) : null,
                        })
                      }
                    />
                    <Select
                      selectedOption={
                        FREQUENCY_OPTIONS.find((o) => o.value === (r.base_rent_frequency ?? '')) ??
                        FREQUENCY_OPTIONS[0]
                      }
                      onChange={({ detail }) =>
                        updateRow(r._uid, {
                          base_rent_frequency:
                            (detail.selectedOption.value as 'monthly' | 'quarterly' | 'annually') ||
                            null,
                        })
                      }
                      options={FREQUENCY_OPTIONS}
                    />
                  </SpaceBetween>
                ),
              width: 240,
            },
            {
              id: 'cam_amount',
              header: 'CAM Amount',
              cell: (r) =>
                importResult ? (
                  <span>{r.amount != null ? `$${Number(r.amount).toLocaleString()}` : '—'}</span>
                ) : (
                  <Input
                    type="number"
                    value={fmt(r.amount)}
                    placeholder="Fixed amount"
                    onChange={({ detail }) =>
                      updateRow(r._uid, { amount: detail.value ? parseFloat(detail.value) : null })
                    }
                  />
                ),
              width: 130,
            },
            {
              id: 'pct_increase',
              header: '% Increase',
              cell: (r) =>
                importResult ? (
                  <span>
                    {r.percent_increase != null
                      ? `${(Number(r.percent_increase) * 100).toFixed(2)}%`
                      : '—'}
                  </span>
                ) : (
                  <Input
                    type="number"
                    value={r.percent_increase != null ? String(Number(r.percent_increase) * 100) : ''}
                    placeholder="% (e.g. 3)"
                    onChange={({ detail }) =>
                      updateRow(r._uid, {
                        percent_increase: detail.value ? parseFloat(detail.value) / 100 : null,
                      })
                    }
                  />
                ),
              width: 110,
            },
            {
              id: 'opex',
              header: 'OpEx',
              cell: (r) =>
                importResult ? (
                  <span>
                    {r.operating_expense_amount != null
                      ? `$${Number(r.operating_expense_amount).toLocaleString()}`
                      : '—'}
                  </span>
                ) : (
                  <Input
                    type="number"
                    value={fmt(r.operating_expense_amount)}
                    placeholder="OpEx"
                    onChange={({ detail }) =>
                      updateRow(r._uid, {
                        operating_expense_amount: detail.value ? parseFloat(detail.value) : null,
                      })
                    }
                  />
                ),
              width: 120,
            },
            {
              id: 'true_up',
              header: 'True-up',
              cell: (r) =>
                importResult ? (
                  <span>
                    {r.reconciliation_true_up != null
                      ? `$${Number(r.reconciliation_true_up).toLocaleString()}`
                      : '—'}
                  </span>
                ) : (
                  <Input
                    type="number"
                    value={fmt(r.reconciliation_true_up)}
                    placeholder="True-up"
                    onChange={({ detail }) =>
                      updateRow(r._uid, {
                        reconciliation_true_up: detail.value ? parseFloat(detail.value) : null,
                      })
                    }
                  />
                ),
              width: 120,
            },
            {
              id: 'notes',
              header: 'Notes',
              cell: (r) =>
                importResult ? (
                  <span>{r.notes || '—'}</span>
                ) : (
                  <Textarea
                    value={r.notes ?? ''}
                    rows={1}
                    onChange={({ detail }) =>
                      updateRow(r._uid, { notes: detail.value || null })
                    }
                  />
                ),
              width: 160,
            },
            {
              id: 'confidence',
              header: 'Confidence',
              cell: (r) => confidenceBadge(r.extraction_confidence),
              width: 100,
            },
            ...(importResult
              ? [
                  {
                    id: 'import_status',
                    header: 'Import status',
                    cell: (r: ReviewRow) => {
                      const s = statusColMap[String(r.year)];
                      return s ? <span>{s}</span> : <span>—</span>;
                    },
                    width: 200,
                  },
                ]
              : []),
          ]}
          empty={<Box textAlign="center">No rows to review.</Box>}
          stripedRows
          variant="embedded"
          wrapLines
        />
      </SpaceBetween>
    </Modal>
  );
};

export default CamHistoryReviewModal;
