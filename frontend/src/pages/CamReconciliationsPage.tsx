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
import Alert from '@cloudscape-design/components/alert';
import { useFlashbar } from '@/context/FlashbarContext';
import { cam as camApi, leases as leasesApi } from '@/api';
import type { CamReconciliation, CamReviewResponse } from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

interface Opt { label: string; value: string; }
interface LineDraft { category: string; actual_amount: string; }

const statusBadge = (s: string) => (
  <Badge color={s === 'finalized' ? 'green' : 'grey'}>{s}</Badge>
);

const severityType = (s: string): 'error' | 'warning' | 'info' =>
  s === 'high' ? 'error' : s === 'medium' ? 'warning' : 'info';

const CamReconciliationsPage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const [recons, setRecons] = useState<CamReconciliation[]>([]);
  const [leaseOpts, setLeaseOpts] = useState<Opt[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<CamReconciliation | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [leaseId, setLeaseId] = useState('');
  const [year, setYear] = useState(String(new Date().getFullYear() - 1));
  const [proRataShare, setProRataShare] = useState('');
  const [grossUpPercent, setGrossUpPercent] = useState('');
  const [estimatedPaid, setEstimatedPaid] = useState('');
  const [capPercent, setCapPercent] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<LineDraft[]>([{ category: '', actual_amount: '' }]);
  const [saving, setSaving] = useState(false);

  const [review, setReview] = useState<CamReviewResponse | null>(null);
  const [reviewing, setReviewing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await camApi.list();
      setRecons(res.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load CAM reconciliations.' });
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
    setYear(String(new Date().getFullYear() - 1));
    setProRataShare('');
    setGrossUpPercent('');
    setEstimatedPaid('');
    setCapPercent('');
    setNotes('');
    setLines([{ category: '', actual_amount: '' }]);
  };

  const updateLine = (idx: number, patch: Partial<LineDraft>) =>
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  const submit = async () => {
    if (!leaseId) {
      addFlash({ type: 'error', content: 'A lease is required.' });
      return;
    }
    const cleanLines = lines
      .filter((l) => l.category.trim() && parseFloat(l.actual_amount) !== 0 && l.actual_amount !== '')
      .map((l) => ({ category: l.category.trim(), actual_amount: parseFloat(l.actual_amount) }));
    setSaving(true);
    try {
      await camApi.create({
        lease_id: leaseId,
        year: Number(year),
        pro_rata_share: proRataShare ? parseFloat(proRataShare) : null,
        gross_up_percent: grossUpPercent ? parseFloat(grossUpPercent) : null,
        estimated_paid: estimatedPaid ? parseFloat(estimatedPaid) : 0,
        cap_percent: capPercent ? parseFloat(capPercent) : null,
        notes: notes || null,
        lines: cleanLines.length ? cleanLines : null,
      });
      addFlash({ type: 'success', content: 'Reconciliation created.' });
      setModalOpen(false);
      resetForm();
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to create reconciliation.' });
    } finally {
      setSaving(false);
    }
  };

  const refreshSelected = (updated: CamReconciliation) => {
    setRecons((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    setSelected((prev) => (prev && prev.id === updated.id ? updated : prev));
  };

  const finalize = async (r: CamReconciliation) => {
    try {
      const res = await camApi.finalize(r.id);
      refreshSelected(res.data);
      addFlash({ type: 'success', content: 'Reconciliation finalized.' });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to finalize.' });
    }
  };

  const postToGl = async (r: CamReconciliation) => {
    try {
      await camApi.postToGl(r.id);
      addFlash({ type: 'success', content: 'Posted to general ledger.' });
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to post to GL.' });
    }
  };

  const remove = async (r: CamReconciliation) => {
    try {
      await camApi.delete(r.id);
      addFlash({ type: 'success', content: 'Reconciliation deleted.' });
      setSelected(null);
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to delete.' });
    }
  };

  const aiReview = async (r: CamReconciliation) => {
    setReviewing(true);
    setReview(null);
    try {
      const res = await camApi.aiReview(r.id);
      setReview(res.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'AI review unavailable.' });
    } finally {
      setReviewing(false);
    }
  };

  const onSelect = (r: CamReconciliation | null) => {
    setSelected(r);
    setReview(null);
  };

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Common-area-maintenance reconciliation: gross-up, caps, base-year offsets, and tenant true-ups posted to the GL."
          actions={<Button variant="primary" onClick={() => setModalOpen(true)}>New reconciliation</Button>}
        >
          CAM Reconciliations
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Table
          loading={loading}
          items={recons}
          selectionType="single"
          selectedItems={selected ? [selected] : []}
          onSelectionChange={({ detail }) => onSelect(detail.selectedItems[0] ?? null)}
          trackBy="id"
          columnDefinitions={[
            { id: 'lease', header: 'Lease', cell: (r) => leaseLabel(r.lease_id) },
            { id: 'year', header: 'Year', cell: (r) => r.year },
            { id: 'pool', header: 'Total pool', cell: (r) => <Box textAlign="right">{fmt(r.total_pool)}</Box> },
            { id: 'recoverable', header: 'Recoverable', cell: (r) => <Box textAlign="right">{fmt(r.recoverable_amount)}</Box> },
            { id: 'paid', header: 'Estimated paid', cell: (r) => <Box textAlign="right">{fmt(r.estimated_paid)}</Box> },
            { id: 'balance', header: 'Balance due', cell: (r) => <Box textAlign="right">{fmt(r.balance_due)}</Box> },
            { id: 'status', header: 'Status', cell: (r) => statusBadge(r.status) },
          ]}
          empty={<Box textAlign="center" color="inherit">No reconciliations yet.</Box>}
        />

        {selected && (
          <Container
            header={
              <Header
                variant="h2"
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={() => aiReview(selected)} loading={reviewing}>AI review</Button>
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
                {leaseLabel(selected.lease_id)} — {selected.year}
              </Header>
            }
          >
            <SpaceBetween size="m">
              <ColumnLayout columns={4} variant="text-grid">
                <div><Box variant="awsui-key-label">Total pool</Box>{fmt(selected.total_pool)}</div>
                <div><Box variant="awsui-key-label">Tenant share</Box>{fmt(selected.tenant_share_amount)}</div>
                <div><Box variant="awsui-key-label">Cap applied</Box>{fmt(selected.cap_applied)}</div>
                <div><Box variant="awsui-key-label">Offset</Box>{fmt(selected.offset_amount)}</div>
                <div><Box variant="awsui-key-label">Recoverable</Box>{fmt(selected.recoverable_amount)}</div>
                <div><Box variant="awsui-key-label">Estimated paid</Box>{fmt(selected.estimated_paid)}</div>
                <div><Box variant="awsui-key-label">Balance due</Box>{fmt(selected.balance_due)}</div>
                <div><Box variant="awsui-key-label">Status</Box>{statusBadge(selected.status)}</div>
              </ColumnLayout>

              <Table
                variant="embedded"
                header={<Header variant="h3">Expense lines</Header>}
                items={selected.lines}
                columnDefinitions={[
                  { id: 'num', header: '#', cell: (l) => l.line_number },
                  { id: 'category', header: 'Category', cell: (l) => l.category },
                  { id: 'controllable', header: 'Controllable', cell: (l) => (l.controllable ? 'Yes' : 'No') },
                  { id: 'actual', header: 'Actual', cell: (l) => <Box textAlign="right">{fmt(l.actual_amount)}</Box> },
                  { id: 'grossed', header: 'Grossed-up', cell: (l) => <Box textAlign="right">{fmt(l.grossed_up_amount)}</Box> },
                ]}
                empty={<Box textAlign="center" color="inherit">No lines.</Box>}
              />

              {review && (
                <Container header={<Header variant="h3">AI review ({review.model})</Header>}>
                  <SpaceBetween size="s">
                    <Box>{review.summary}</Box>
                    {review.anomalies.length === 0 ? (
                      <Alert type="success">No anomalies flagged.</Alert>
                    ) : (
                      review.anomalies.map((a, i) => (
                        <Alert key={i} type={severityType(a.severity)} header={`${a.category || a.anomaly_type} (${a.severity})`}>
                          <SpaceBetween size="xxs">
                            <Box>{a.message}</Box>
                            {a.recommendation && <Box color="text-body-secondary">{a.recommendation}</Box>}
                          </SpaceBetween>
                        </Alert>
                      ))
                    )}
                  </SpaceBetween>
                </Container>
              )}
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header="New CAM reconciliation"
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
            <FormField label="Year">
              <Input type="number" value={year} onChange={({ detail }) => setYear(detail.value)} />
            </FormField>
          </ColumnLayout>
          <ColumnLayout columns={2}>
            <FormField label="Pro-rata share (0–1)" description="Optional; derived from square footage when omitted.">
              <Input type="number" value={proRataShare} onChange={({ detail }) => setProRataShare(detail.value)} />
            </FormField>
            <FormField label="Gross-up percent">
              <Input type="number" value={grossUpPercent} onChange={({ detail }) => setGrossUpPercent(detail.value)} />
            </FormField>
            <FormField label="Cap percent">
              <Input type="number" value={capPercent} onChange={({ detail }) => setCapPercent(detail.value)} />
            </FormField>
            <FormField label="Estimated paid">
              <Input type="number" value={estimatedPaid} onChange={({ detail }) => setEstimatedPaid(detail.value)} />
            </FormField>
          </ColumnLayout>
          <FormField label="Notes">
            <Input value={notes} onChange={({ detail }) => setNotes(detail.value)} />
          </FormField>
          <FormField
            label="Expense lines"
            description="Leave empty to seed from the lease-year's operating expenses."
          >
            <SpaceBetween size="xs">
              {lines.map((line, idx) => (
                <ColumnLayout key={idx} columns={2}>
                  <Input
                    value={line.category}
                    placeholder="Category (e.g. landscaping)"
                    onChange={({ detail }) => updateLine(idx, { category: detail.value })}
                  />
                  <SpaceBetween direction="horizontal" size="xs">
                    <Input
                      type="number"
                      value={line.actual_amount}
                      placeholder="Actual amount"
                      onChange={({ detail }) => updateLine(idx, { actual_amount: detail.value })}
                    />
                    {lines.length > 1 && (
                      <Button
                        iconName="remove"
                        variant="icon"
                        ariaLabel="Remove line"
                        onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))}
                      />
                    )}
                  </SpaceBetween>
                </ColumnLayout>
              ))}
              <Button
                iconName="add-plus"
                onClick={() => setLines((prev) => [...prev, { category: '', actual_amount: '' }])}
              >
                Add line
              </Button>
            </SpaceBetween>
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default CamReconciliationsPage;
