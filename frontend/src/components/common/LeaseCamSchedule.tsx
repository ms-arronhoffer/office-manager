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
import { leases as leasesApi, gl as glApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type { LeaseCamEntry, LeaseCamEntryInput, GLAccountOption } from '@/types';

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
}

const emptyForm = (): CamFormState => ({
  year: String(new Date().getFullYear()),
  charge_type: 'fixed',
  amount: '',
  percent_increase: '',
  gl_account_id: '',
  notes: '',
});

const CHARGE_TYPE_OPTIONS = [
  { value: 'fixed', label: 'Fixed amount' },
  { value: 'percent_increase', label: 'Percent increase (over prior year)' },
];

const formatAmount = (v: number | null): string =>
  v != null ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

const formatPercent = (v: number | null): string =>
  v != null ? `${(Number(v) * 100).toLocaleString(undefined, { maximumFractionDigits: 4 })}%` : '—';

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
      .catch(() => {
        // non-critical
      });
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
    });
    setModalVisible(true);
  };

  const buildPayload = (): LeaseCamEntryInput => {
    const payload: LeaseCamEntryInput = {
      year: parseInt(form.year, 10),
      charge_type: form.charge_type,
      gl_account_id: form.gl_account_id || null,
      notes: form.notes.trim() || null,
    };
    if (form.charge_type === 'fixed') {
      payload.amount = form.amount.trim() ? form.amount.trim() : null;
      payload.percent_increase = null;
    } else {
      // User enters a whole percent (e.g. 3 => 0.03)
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

  const sortedEntries = useMemo(
    () => [...entries].sort((a, b) => a.year - b.year),
    [entries],
  );

  return (
    <>
      <Modal
        visible={modalVisible}
        onDismiss={() => setModalVisible(false)}
        header={editingId ? 'Edit CAM Entry' : 'Add CAM Entry'}
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
          <FormField label="Year">
            <Input
              type="number"
              value={form.year}
              onChange={({ detail }) => setForm((p) => ({ ...p, year: detail.value }))}
              placeholder="e.g., 2020"
            />
          </FormField>
          <FormField label="Charge Type">
            <Select
              selectedOption={
                CHARGE_TYPE_OPTIONS.find((o) => o.value === form.charge_type) ?? CHARGE_TYPE_OPTIONS[0]
              }
              onChange={({ detail }) =>
                setForm((p) => ({ ...p, charge_type: (detail.selectedOption.value as ChargeType) ?? 'fixed' }))
              }
              options={CHARGE_TYPE_OPTIONS}
            />
          </FormField>
          {form.charge_type === 'fixed' ? (
            <FormField label="Amount" description="Fixed CAM charge for the year.">
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
          <FormField label="GL Account" description="Optional general-ledger account for this CAM charge.">
            <Select
              selectedOption={glOptions.find((o) => o.value === form.gl_account_id) ?? glOptions[0]}
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
          <SpaceBetween size="m">
            {canEdit && (
              <Box float="right">
                <Button variant="primary" onClick={openCreate}>
                  Add CAM Entry
                </Button>
              </Box>
            )}
            <Table
              columnDefinitions={[
                { id: 'year', header: 'Year', cell: (e: LeaseCamEntry) => e.year },
                {
                  id: 'charge_type',
                  header: 'Charge Type',
                  cell: (e: LeaseCamEntry) =>
                    e.charge_type === 'percent_increase' ? 'Percent increase' : 'Fixed amount',
                },
                {
                  id: 'value',
                  header: 'Amount / Increase',
                  cell: (e: LeaseCamEntry) =>
                    e.charge_type === 'percent_increase'
                      ? formatPercent(e.percent_increase)
                      : formatAmount(e.amount),
                },
                {
                  id: 'gl',
                  header: 'GL Account',
                  cell: (e: LeaseCamEntry) =>
                    e.gl_account ? `${e.gl_account.code} — ${e.gl_account.name}` : '—',
                },
                { id: 'notes', header: 'Notes', cell: (e: LeaseCamEntry) => e.notes || '—' },
                ...(canEdit
                  ? [
                      {
                        id: 'actions',
                        header: 'Actions',
                        cell: (e: LeaseCamEntry) => (
                          <SpaceBetween direction="horizontal" size="xs">
                            <Button onClick={() => openEdit(e)}>Edit</Button>
                            <Button
                              variant="inline-link"
                              loading={deletingId === e.id}
                              onClick={() => handleDelete(e)}
                            >
                              Delete
                            </Button>
                          </SpaceBetween>
                        ),
                      },
                    ]
                  : []),
              ]}
              items={sortedEntries}
              empty={
                <Box textAlign="center" color="inherit" padding="m">
                  No CAM entries recorded. Click "Add CAM Entry" to build a per-year CAM schedule.
                </Box>
              }
            />
          </SpaceBetween>
        )}
      </ExpandableSection>
    </>
  );
};

export default LeaseCamSchedule;
