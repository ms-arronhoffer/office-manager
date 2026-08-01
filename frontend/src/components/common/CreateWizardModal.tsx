import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Wizard from '@cloudscape-design/components/wizard';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Table from '@cloudscape-design/components/table';
import Textarea from '@cloudscape-design/components/textarea';
import FormField from '@cloudscape-design/components/form-field';
import SpaceBetween from '@cloudscape-design/components/space-between';
import SegmentedControl from '@cloudscape-design/components/segmented-control';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import { wizardI18nStrings } from '@/components/common/wizardI18n';
import useUnsavedChangesWarning from '@/hooks/useUnsavedChangesWarning';
import { parseDelimitedRows } from '@/lib/delimited';

export interface CreateWizardStep {
  title: string;
  description?: string;
  content: React.ReactNode;
  /** Return a message to block leaving this step, or null when it is valid. */
  validate?: () => string | null;
}

export interface BulkColumn {
  /** Key handed back in each parsed row. */
  key: string;
  label: string;
  required?: boolean;
}

export interface BulkInsertConfig {
  columns: BulkColumn[];
  /** Create a single record. Called once per parsed row, in order. */
  onSubmitRow: (row: Record<string, string>) => Promise<void>;
}

export interface CreateWizardModalProps {
  visible: boolean;
  /** Lowercase singular noun, e.g. "resident". Drives titles and labels. */
  entityLabel: string;
  steps: CreateWizardStep[];
  onSubmit: () => Promise<void> | void;
  onCancel: () => void;
  /** Called after a successful bulk import so the caller can refresh. */
  onBulkComplete?: () => void;
  submitting?: boolean;
  error?: string | null;
  /** Offers a "Bulk add" mode alongside the guided steps. */
  bulk?: BulkInsertConfig;
  /** True when the user has entered data worth warning about on exit. */
  dirty?: boolean;
  size?: 'medium' | 'large' | 'max';
}

type Mode = 'guided' | 'bulk';

interface RowResult {
  line: number;
  values: Record<string, string>;
  status: 'pending' | 'ok' | 'error';
  message?: string;
}

/**
 * Guided, step-by-step creation flow shared by every "add" action, mirroring
 * the office and lease wizards. Editing keeps using the plain form modal.
 */
const CreateWizardModal: React.FC<CreateWizardModalProps> = ({
  visible,
  entityLabel,
  steps,
  onSubmit,
  onCancel,
  onBulkComplete,
  submitting = false,
  error,
  bulk,
  dirty = false,
  size = 'large',
}) => {
  const [mode, setMode] = useState<Mode>('guided');
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [stepError, setStepError] = useState<string | null>(null);

  const [pasted, setPasted] = useState('');
  const [rows, setRows] = useState<RowResult[]>([]);
  const [importing, setImporting] = useState(false);
  const [importDone, setImportDone] = useState(0);

  const bulkDirty = pasted.trim() !== '' && !importing;
  useUnsavedChangesWarning(visible && !submitting && (dirty || bulkDirty));

  // Reset transient wizard state each time the modal is opened.
  useEffect(() => {
    if (visible) {
      setMode('guided');
      setActiveStepIndex(0);
      setStepError(null);
      setPasted('');
      setRows([]);
      setImporting(false);
      setImportDone(0);
    }
  }, [visible]);

  const requestCancel = useCallback(() => {
    if ((dirty || bulkDirty) && !window.confirm(`Discard this new ${entityLabel}?`)) return;
    onCancel();
  }, [dirty, bulkDirty, entityLabel, onCancel]);

  const wizardSteps = useMemo(
    () =>
      steps.map((step) => ({
        title: step.title,
        description: step.description,
        content: (
          <SpaceBetween size="m">
            {stepError && <Alert type="error">{stepError}</Alert>}
            {step.content}
          </SpaceBetween>
        ),
      })),
    [steps, stepError],
  );

  const handleNavigate = useCallback(
    (requestedStepIndex: number) => {
      // Only validate when moving forward so users can always go back.
      if (requestedStepIndex > activeStepIndex) {
        for (let i = activeStepIndex; i < requestedStepIndex; i += 1) {
          const message = steps[i]?.validate?.() ?? null;
          if (message) {
            setStepError(message);
            setActiveStepIndex(i);
            return;
          }
        }
      }
      setStepError(null);
      setActiveStepIndex(requestedStepIndex);
    },
    [activeStepIndex, steps],
  );

  const handleSubmit = useCallback(async () => {
    const message = steps[activeStepIndex]?.validate?.() ?? null;
    if (message) {
      setStepError(message);
      return;
    }
    setStepError(null);
    await onSubmit();
  }, [activeStepIndex, steps, onSubmit]);

  const parseBulk = useCallback(() => {
    if (!bulk) return;
    const parsed = parseDelimitedRows(pasted, bulk.columns.map((c) => c.key));
    setRows(
      parsed.map((values, index) => {
        const missing = bulk.columns
          .filter((c) => c.required && !values[c.key]?.trim())
          .map((c) => c.label);
        return {
          line: index + 1,
          values,
          status: missing.length ? ('error' as const) : ('pending' as const),
          message: missing.length ? `Missing ${missing.join(', ')}` : undefined,
        };
      }),
    );
    setImportDone(0);
  }, [bulk, pasted]);

  const runBulkImport = useCallback(async () => {
    if (!bulk) return;
    setImporting(true);
    setImportDone(0);
    const next = [...rows];
    for (let i = 0; i < next.length; i += 1) {
      if (next[i].status === 'error') continue;
      try {
        await bulk.onSubmitRow(next[i].values);
        next[i] = { ...next[i], status: 'ok' };
      } catch (err) {
        next[i] = {
          ...next[i],
          status: 'error',
          message: err instanceof Error ? err.message : 'Failed to create',
        };
      }
      setImportDone(i + 1);
      setRows([...next]);
    }
    setImporting(false);
    onBulkComplete?.();
  }, [bulk, rows, onBulkComplete]);

  const importable = rows.filter((r) => r.status !== 'error').length;
  const succeeded = rows.filter((r) => r.status === 'ok').length;
  const failed = rows.filter((r) => r.status === 'error').length;

  if (!visible) return null;

  return (
    <Modal
      visible={visible}
      onDismiss={requestCancel}
      size={size}
      header={`Add ${entityLabel}`}
      footer={
        mode === 'bulk' ? (
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={requestCancel} disabled={importing}>
                {succeeded > 0 ? 'Close' : 'Cancel'}
              </Button>
              <Button onClick={parseBulk} disabled={!pasted.trim() || importing}>
                Preview
              </Button>
              <Button
                variant="primary"
                onClick={runBulkImport}
                loading={importing}
                disabled={importable === 0 || importing}
              >
                {`Create ${importable} ${entityLabel}${importable === 1 ? '' : 's'}`}
              </Button>
            </SpaceBetween>
          </Box>
        ) : undefined
      }
    >
      <SpaceBetween size="m">
        {bulk && (
          <SegmentedControl
            selectedId={mode}
            onChange={({ detail }) => setMode(detail.selectedId as Mode)}
            label="Creation mode"
            options={[
              { id: 'guided', text: 'Guided' },
              { id: 'bulk', text: 'Bulk add' },
            ]}
          />
        )}

        {error && <Alert type="error">{error}</Alert>}

        {mode === 'guided' ? (
          <Wizard
            steps={wizardSteps}
            activeStepIndex={activeStepIndex}
            i18nStrings={wizardI18nStrings(`Create ${entityLabel}`)}
            isLoadingNextStep={submitting}
            onNavigate={({ detail }) => handleNavigate(detail.requestedStepIndex)}
            onCancel={requestCancel}
            onSubmit={handleSubmit}
          />
        ) : (
          bulk && (
            <SpaceBetween size="m">
              <FormField
                label="Paste rows"
                description={`One ${entityLabel} per line. Copy straight from a spreadsheet, or use comma-separated values. Columns, in order: ${bulk.columns
                  .map((c) => `${c.label}${c.required ? '*' : ''}`)
                  .join(', ')}.`}
              >
                <Textarea
                  value={pasted}
                  onChange={({ detail }) => setPasted(detail.value)}
                  rows={6}
                  placeholder={bulk.columns.map((c) => c.label).join('\t')}
                  disabled={importing}
                />
              </FormField>

              {importing && (
                <ProgressBar
                  value={rows.length ? Math.round((importDone / rows.length) * 100) : 0}
                  additionalInfo={`${importDone} of ${rows.length} processed`}
                  label="Creating records"
                />
              )}

              {rows.length > 0 && (
                <>
                  {succeeded > 0 && (
                    <Alert type={failed ? 'warning' : 'success'}>
                      {`Created ${succeeded} of ${rows.length}.`}
                      {failed ? ` ${failed} row(s) need attention.` : ''}
                    </Alert>
                  )}
                  <Table
                    variant="embedded"
                    items={rows}
                    columnDefinitions={[
                      { id: 'line', header: '#', cell: (r) => r.line, width: 60 },
                      ...bulk.columns.map((c) => ({
                        id: c.key,
                        header: c.label,
                        cell: (r: RowResult) => r.values[c.key] || '—',
                      })),
                      {
                        id: 'status',
                        header: 'Status',
                        cell: (r: RowResult) =>
                          r.status === 'ok' ? (
                            <StatusIndicator type="success">Created</StatusIndicator>
                          ) : r.status === 'error' ? (
                            <StatusIndicator type="error">{r.message ?? 'Error'}</StatusIndicator>
                          ) : (
                            <StatusIndicator type="pending">Ready</StatusIndicator>
                          ),
                      },
                    ]}
                    empty={<Box textAlign="center">Nothing parsed yet.</Box>}
                  />
                </>
              )}
            </SpaceBetween>
          )
        )}
      </SpaceBetween>
    </Modal>
  );
};

export default CreateWizardModal;
