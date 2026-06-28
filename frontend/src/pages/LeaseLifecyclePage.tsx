import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { lifecycle as lifecycleApi, leases as leasesApi } from '@/api';
import type { LifecycleEvent } from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const today = () => new Date().toISOString().slice(0, 10);

interface Opt { label: string; value: string; }

const EVENT_TYPES: Opt[] = [
  { label: 'Modification', value: 'modification' },
  { label: 'Renewal / option exercise', value: 'renewal' },
  { label: 'Partial termination', value: 'partial_termination' },
  { label: 'Full termination', value: 'termination' },
];

const eventLabel = (v: string) =>
  EVENT_TYPES.find((o) => o.value === v)?.label ?? v;

const statusBadge = (s: string) => (
  <Badge color={s === 'finalized' ? 'green' : 'grey'}>{s}</Badge>
);

const isTermination = (t: string) => t === 'termination' || t === 'partial_termination';

const LeaseLifecyclePage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const [events, setEvents] = useState<LifecycleEvent[]>([]);
  const [leaseOpts, setLeaseOpts] = useState<Opt[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<LifecycleEvent | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [leaseId, setLeaseId] = useState('');
  const [eventType, setEventType] = useState<Opt>(EVENT_TYPES[0]);
  const [effectiveDate, setEffectiveDate] = useState(today());
  const [newPaymentAmount, setNewPaymentAmount] = useState('');
  const [newEscalationRate, setNewEscalationRate] = useState('');
  const [newBorrowingRate, setNewBorrowingRate] = useState('');
  const [remainingTermMonths, setRemainingTermMonths] = useState('');
  const [remainingPercentage, setRemainingPercentage] = useState('');
  const [terminationPenalty, setTerminationPenalty] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await lifecycleApi.list();
      setEvents(res.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load lifecycle events.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    leasesApi.list({ page_size: 1000 }).then((res) => {
      setLeaseOpts(res.data.items.map((l) => ({ label: l.lease_name, value: l.id })));
    }).catch(() => {});
  }, []);

  const leaseLabel = useCallback(
    (id: string) => leaseOpts.find((o) => o.value === id)?.label ?? id,
    [leaseOpts],
  );

  const resetForm = () => {
    setLeaseId('');
    setEventType(EVENT_TYPES[0]);
    setEffectiveDate(today());
    setNewPaymentAmount('');
    setNewEscalationRate('');
    setNewBorrowingRate('');
    setRemainingTermMonths('');
    setRemainingPercentage('');
    setTerminationPenalty('');
    setNotes('');
  };

  const submit = async () => {
    if (!leaseId) {
      addFlash({ type: 'error', content: 'A lease is required.' });
      return;
    }
    setSaving(true);
    try {
      await lifecycleApi.create({
        lease_id: leaseId,
        event_type: eventType.value,
        effective_date: effectiveDate,
        new_payment_amount: newPaymentAmount ? parseFloat(newPaymentAmount) : null,
        new_annual_escalation_rate: newEscalationRate ? parseFloat(newEscalationRate) : null,
        new_incremental_borrowing_rate: newBorrowingRate ? parseFloat(newBorrowingRate) : null,
        remaining_term_months: remainingTermMonths ? parseInt(remainingTermMonths, 10) : null,
        remaining_percentage: remainingPercentage ? parseFloat(remainingPercentage) : null,
        termination_penalty: terminationPenalty ? parseFloat(terminationPenalty) : 0,
        notes: notes || null,
      });
      addFlash({ type: 'success', content: 'Lifecycle event created.' });
      setModalOpen(false);
      resetForm();
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to create event.' });
    } finally {
      setSaving(false);
    }
  };

  const refreshSelected = (updated: LifecycleEvent) => {
    setEvents((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    setSelected((prev) => (prev && prev.id === updated.id ? updated : prev));
  };

  const finalize = async (ev: LifecycleEvent) => {
    try {
      const res = await lifecycleApi.finalize(ev.id);
      refreshSelected(res.data);
      addFlash({ type: 'success', content: 'Event finalized.' });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to finalize.' });
    }
  };

  const postToGl = async (ev: LifecycleEvent) => {
    try {
      await lifecycleApi.postToGl(ev.id);
      addFlash({ type: 'success', content: 'Posted to general ledger.' });
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to post to GL.' });
    }
  };

  const remove = async (ev: LifecycleEvent) => {
    try {
      await lifecycleApi.delete(ev.id);
      addFlash({ type: 'success', content: 'Event deleted.' });
      setSelected(null);
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to delete.' });
    }
  };

  const termination = useMemo(() => isTermination(eventType.value), [eventType.value]);

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="ASC 842 / IFRS 16 post-commencement remeasurements: modifications, renewals, and terminations posted to the GL."
          actions={<Button variant="primary" onClick={() => setModalOpen(true)}>New event</Button>}
        >
          Lease Lifecycle Accounting
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Table
          loading={loading}
          items={events}
          selectionType="single"
          selectedItems={selected ? [selected] : []}
          onSelectionChange={({ detail }) => setSelected(detail.selectedItems[0] ?? null)}
          trackBy="id"
          columnDefinitions={[
            { id: 'lease', header: 'Lease', cell: (e) => leaseLabel(e.lease_id) },
            { id: 'type', header: 'Event', cell: (e) => eventLabel(e.event_type) },
            { id: 'date', header: 'Effective', cell: (e) => e.effective_date },
            { id: 'liability', header: 'Liability adj.', cell: (e) => <Box textAlign="right">{fmt(e.liability_adjustment)}</Box> },
            { id: 'rou', header: 'ROU adj.', cell: (e) => <Box textAlign="right">{fmt(e.rou_adjustment)}</Box> },
            { id: 'gainloss', header: 'Gain / loss', cell: (e) => <Box textAlign="right">{fmt(e.gain_loss)}</Box> },
            { id: 'status', header: 'Status', cell: (e) => statusBadge(e.status) },
          ]}
          empty={<Box textAlign="center" color="inherit">No lifecycle events yet.</Box>}
        />

        {selected && (
          <Container
            header={
              <Header
                variant="h2"
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    {selected.status === 'draft' && (
                      <>
                        <Button onClick={() => remove(selected)}>Delete</Button>
                        <Button variant="primary" onClick={() => finalize(selected)}>Finalize</Button>
                      </>
                    )}
                    {selected.status === 'finalized' && !selected.journal_entry_id && (
                      <Button variant="primary" onClick={() => postToGl(selected)}>Post to GL</Button>
                    )}
                  </SpaceBetween>
                }
              >
                {leaseLabel(selected.lease_id)} — {eventLabel(selected.event_type)}
              </Header>
            }
          >
            <ColumnLayout columns={4} variant="text-grid">
              <div><Box variant="awsui-key-label">Pre liability</Box>{fmt(selected.pre_liability)}</div>
              <div><Box variant="awsui-key-label">Pre ROU</Box>{fmt(selected.pre_rou)}</div>
              <div><Box variant="awsui-key-label">Revised liability</Box>{fmt(selected.revised_liability)}</div>
              <div><Box variant="awsui-key-label">Liability adjustment</Box>{fmt(selected.liability_adjustment)}</div>
              <div><Box variant="awsui-key-label">ROU adjustment</Box>{fmt(selected.rou_adjustment)}</div>
              <div><Box variant="awsui-key-label">Post liability</Box>{fmt(selected.post_liability)}</div>
              <div><Box variant="awsui-key-label">Post ROU</Box>{fmt(selected.post_rou)}</div>
              <div><Box variant="awsui-key-label">Gain / loss</Box>{fmt(selected.gain_loss)}</div>
            </ColumnLayout>
          </Container>
        )}
      </SpaceBetween>

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header="New lifecycle event"
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={saving} onClick={submit}>Create</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <ColumnLayout columns={2}>
            <FormField label="Lease">
              <Select
                selectedOption={leaseId ? leaseOpts.find((o) => o.value === leaseId) ?? null : null}
                options={leaseOpts}
                onChange={({ detail }) => setLeaseId(detail.selectedOption.value ?? '')}
                filteringType="auto"
                placeholder="Select a lease"
                empty="No leases"
              />
            </FormField>
            <FormField label="Event type">
              <Select
                selectedOption={eventType}
                options={EVENT_TYPES}
                onChange={({ detail }) => setEventType(detail.selectedOption as Opt)}
              />
            </FormField>
          </ColumnLayout>
          <FormField label="Effective date">
            <Input type="date" value={effectiveDate} onChange={({ detail }) => setEffectiveDate(detail.value)} />
          </FormField>

          {!termination && (
            <ColumnLayout columns={2}>
              <FormField label="New payment amount" description="Per-period payment after the change.">
                <Input type="number" value={newPaymentAmount} onChange={({ detail }) => setNewPaymentAmount(detail.value)} />
              </FormField>
              <FormField label="Remaining term (months)">
                <Input type="number" value={remainingTermMonths} onChange={({ detail }) => setRemainingTermMonths(detail.value)} />
              </FormField>
              <FormField label="New annual escalation rate">
                <Input type="number" value={newEscalationRate} onChange={({ detail }) => setNewEscalationRate(detail.value)} />
              </FormField>
              <FormField label="New incremental borrowing rate">
                <Input type="number" value={newBorrowingRate} onChange={({ detail }) => setNewBorrowingRate(detail.value)} />
              </FormField>
            </ColumnLayout>
          )}

          {termination && (
            <ColumnLayout columns={2}>
              <FormField label="Remaining percentage (0–1)" description="Share of the lease that remains after a partial termination.">
                <Input type="number" value={remainingPercentage} onChange={({ detail }) => setRemainingPercentage(detail.value)} />
              </FormField>
              <FormField label="Termination penalty">
                <Input type="number" value={terminationPenalty} onChange={({ detail }) => setTerminationPenalty(detail.value)} />
              </FormField>
            </ColumnLayout>
          )}

          <FormField label="Notes">
            <Input value={notes} onChange={({ detail }) => setNotes(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default LeaseLifecyclePage;
