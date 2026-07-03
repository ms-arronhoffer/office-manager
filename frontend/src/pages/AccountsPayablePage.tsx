import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import EntityFormModal from '@/components/common/EntityFormModal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { ap as apApi, vendors as vendorsApi, gl as glApi } from '@/api';
import type { VendorBill, GLAccount } from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const today = () => new Date().toISOString().slice(0, 10);

interface Opt { label: string; value: string; }
interface LineDraft { account_id: string; amount: string; description: string; }

const stateBadge = (s: string) => {
  const color = s === 'paid' ? 'green' : s === 'partial' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

const statusBadge = (s: string) => {
  const color = s === 'finalized' ? 'green' : s === 'void' ? 'red' : 'grey';
  return <Badge color={color as 'green' | 'red' | 'grey'}>{s}</Badge>;
};

const AccountsPayablePage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const [bills, setBills] = useState<VendorBill[]>([]);
  const [vendorOpts, setVendorOpts] = useState<Opt[]>([]);
  const [accounts, setAccounts] = useState<GLAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<VendorBill | null>(null);

  // Bill modal
  const [billModalOpen, setBillModalOpen] = useState(false);
  const [vendorId, setVendorId] = useState('');
  const [billDate, setBillDate] = useState(today());
  const [dueDate, setDueDate] = useState('');
  const [billNumber, setBillNumber] = useState('');
  const [memo, setMemo] = useState('');
  const [lines, setLines] = useState<LineDraft[]>([{ account_id: '', amount: '', description: '' }]);
  const [savingBill, setSavingBill] = useState(false);

  // Payment modal
  const [payModalOpen, setPayModalOpen] = useState(false);
  const [payBill, setPayBill] = useState<VendorBill | null>(null);
  const [payDate, setPayDate] = useState(today());
  const [payAmount, setPayAmount] = useState('');
  const [payMethod, setPayMethod] = useState('');
  const [payReference, setPayReference] = useState('');
  const [savingPay, setSavingPay] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apApi.listBills();
      setBills(res.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load bills.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    vendorsApi.list({ page_size: 1000 }).then((res) => {
      setVendorOpts(res.data.items.map((v) => ({ label: v.company_name, value: v.id })));
    }).catch(() => {});
    glApi.listAccounts().then((res) => setAccounts(res.data)).catch(() => {});
  }, []);

  const accountOptions = useMemo<Opt[]>(
    () => accounts.filter((a) => a.is_active).map((a) => ({ label: `${a.code} — ${a.name}`, value: a.id })),
    [accounts],
  );
  const accountLabel = useCallback(
    (id: string) => accountOptions.find((o) => o.value === id)?.label ?? id,
    [accountOptions],
  );
  const vendorLabel = useCallback(
    (id: string) => vendorOpts.find((o) => o.value === id)?.label ?? id,
    [vendorOpts],
  );

  const resetBillForm = () => {
    setVendorId('');
    setBillDate(today());
    setDueDate('');
    setBillNumber('');
    setMemo('');
    setLines([{ account_id: '', amount: '', description: '' }]);
  };

  const updateLine = (idx: number, patch: Partial<LineDraft>) =>
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  const billTotal = useMemo(
    () => lines.reduce((s, l) => s + (parseFloat(l.amount) || 0), 0),
    [lines],
  );

  const submitBill = async () => {
    const cleanLines = lines
      .filter((l) => l.account_id && parseFloat(l.amount) > 0)
      .map((l) => ({
        account_id: l.account_id,
        amount: parseFloat(l.amount),
        description: l.description || null,
      }));
    if (!vendorId) {
      addFlash({ type: 'error', content: 'A vendor is required.' });
      return;
    }
    if (cleanLines.length === 0) {
      addFlash({ type: 'error', content: 'Add at least one expense line with an account and amount.' });
      return;
    }
    setSavingBill(true);
    try {
      await apApi.createBill({
        vendor_id: vendorId,
        bill_date: billDate,
        due_date: dueDate || null,
        bill_number: billNumber || null,
        memo: memo || null,
        lines: cleanLines,
      });
      addFlash({ type: 'success', content: 'Bill created.' });
      setBillModalOpen(false);
      resetBillForm();
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to create bill.' });
    } finally {
      setSavingBill(false);
    }
  };

  const refreshSelected = (updated: VendorBill) => {
    setBills((prev) => prev.map((b) => (b.id === updated.id ? updated : b)));
    setSelected((prev) => (prev && prev.id === updated.id ? updated : prev));
  };

  const runAction = async (label: string, fn: () => Promise<{ data: VendorBill }>) => {
    try {
      const res = await fn();
      refreshSelected(res.data);
      addFlash({ type: 'success', content: label });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Action failed.' });
    }
  };

  const finalizeBill = (b: VendorBill) =>
    runAction('Bill finalized and posted to GL.', () => apApi.finalizeBill(b.id));

  const voidBill = (b: VendorBill) =>
    runAction('Bill voided.', () => apApi.voidBill(b.id));

  const deleteBill = async (b: VendorBill) => {
    try {
      await apApi.deleteBill(b.id);
      addFlash({ type: 'success', content: 'Bill deleted.' });
      setSelected(null);
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to delete bill.' });
    }
  };

  const openPayment = (b: VendorBill) => {
    setPayBill(b);
    setPayDate(today());
    setPayAmount(String(b.balance_due));
    setPayMethod('');
    setPayReference('');
    setPayModalOpen(true);
  };

  const submitPayment = async () => {
    if (!payBill) return;
    const amount = parseFloat(payAmount);
    if (!(amount > 0)) {
      addFlash({ type: 'error', content: 'Payment amount must be greater than zero.' });
      return;
    }
    setSavingPay(true);
    try {
      const res = await apApi.createPayment(payBill.id, {
        payment_date: payDate,
        amount,
        method: payMethod || null,
        reference: payReference || null,
      });
      refreshSelected(res.data);
      addFlash({ type: 'success', content: 'Payment recorded.' });
      setPayModalOpen(false);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to record payment.' });
    } finally {
      setSavingPay(false);
    }
  };

  const deletePayment = (paymentId: string) =>
    runAction('Payment removed.', () => apApi.deletePayment(paymentId));

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Vendor bills and payments posting to the audit-grade general ledger."
          actions={<Button variant="primary" onClick={() => setBillModalOpen(true)}>New bill</Button>}
        >
          Accounts Payable
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Table
          loading={loading}
          items={bills}
          selectionType="single"
          selectedItems={selected ? [selected] : []}
          onSelectionChange={({ detail }) => setSelected(detail.selectedItems[0] ?? null)}
          trackBy="id"
          columnDefinitions={[
            { id: 'vendor', header: 'Vendor', cell: (b) => vendorLabel(b.vendor_id) },
            { id: 'number', header: 'Bill #', cell: (b) => b.bill_number || '—' },
            { id: 'date', header: 'Bill date', cell: (b) => b.bill_date },
            { id: 'due', header: 'Due', cell: (b) => b.due_date || '—' },
            { id: 'total', header: 'Total', cell: (b) => <Box textAlign="right">{fmt(b.total_amount)}</Box> },
            { id: 'paid', header: 'Paid', cell: (b) => <Box textAlign="right">{fmt(b.amount_paid)}</Box> },
            { id: 'balance', header: 'Balance', cell: (b) => <Box textAlign="right">{fmt(b.balance_due)}</Box> },
            { id: 'paystate', header: 'Payment', cell: (b) => stateBadge(b.payment_state) },
            { id: 'status', header: 'Status', cell: (b) => statusBadge(b.status) },
          ]}
          empty={<Box textAlign="center" color="inherit">No bills yet.</Box>}
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
                        <Button onClick={() => deleteBill(selected)}>Delete</Button>
                        <Button variant="primary" onClick={() => finalizeBill(selected)}>Finalize &amp; post</Button>
                      </>
                    )}
                    {selected.status === 'finalized' && (
                      <>
                        {selected.balance_due > 0 && (
                          <Button variant="primary" onClick={() => openPayment(selected)}>Record payment</Button>
                        )}
                        {selected.amount_paid === 0 && (
                          <Button onClick={() => voidBill(selected)}>Void</Button>
                        )}
                      </>
                    )}
                  </SpaceBetween>
                }
              >
                Bill — {vendorLabel(selected.vendor_id)}
              </Header>
            }
          >
            <SpaceBetween size="m">
              <ColumnLayout columns={4} variant="text-grid">
                <div><Box variant="awsui-key-label">Total</Box>{fmt(selected.total_amount)}</div>
                <div><Box variant="awsui-key-label">Paid</Box>{fmt(selected.amount_paid)}</div>
                <div><Box variant="awsui-key-label">Balance</Box>{fmt(selected.balance_due)}</div>
                <div><Box variant="awsui-key-label">Status</Box>{statusBadge(selected.status)}</div>
              </ColumnLayout>

              <Table
                variant="embedded"
                header={<Header variant="h3">Expense lines</Header>}
                items={selected.lines}
                columnDefinitions={[
                  { id: 'num', header: '#', cell: (l) => l.line_number },
                  { id: 'account', header: 'Account', cell: (l) => accountLabel(l.account_id) },
                  { id: 'desc', header: 'Description', cell: (l) => l.description || '—' },
                  { id: 'amount', header: 'Amount', cell: (l) => <Box textAlign="right">{fmt(l.amount)}</Box> },
                ]}
                empty={<Box textAlign="center" color="inherit">No lines.</Box>}
              />

              <Table
                variant="embedded"
                header={<Header variant="h3">Payments</Header>}
                items={selected.payments}
                columnDefinitions={[
                  { id: 'date', header: 'Date', cell: (p) => p.payment_date },
                  { id: 'amount', header: 'Amount', cell: (p) => <Box textAlign="right">{fmt(p.amount)}</Box> },
                  { id: 'method', header: 'Method', cell: (p) => p.method || '—' },
                  { id: 'reference', header: 'Reference', cell: (p) => p.reference || '—' },
                  {
                    id: 'actions',
                    header: '',
                    cell: (p) => <Button variant="inline-link" onClick={() => deletePayment(p.id)}>Remove</Button>,
                  },
                ]}
                empty={<Box textAlign="center" color="inherit">No payments recorded.</Box>}
              />
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>

      {/* New bill modal */}
      <EntityFormModal
        visible={billModalOpen}
        title="New vendor bill"
        onCancel={() => setBillModalOpen(false)}
        onSubmit={submitBill}
        submitting={savingBill}
        submitLabel="Create"
        size="large"
      >
        <SpaceBetween size="m">
          <FormField label="Vendor">
            <Select
              selectedOption={vendorId ? vendorOpts.find((o) => o.value === vendorId) ?? null : null}
              options={vendorOpts}
              onChange={({ detail }) => setVendorId(detail.selectedOption.value ?? '')}
              filteringType="auto"
              placeholder="Select a vendor"
              empty="No vendors"
            />
          </FormField>
          <ColumnLayout columns={3}>
            <FormField label="Bill date">
              <Input type="date" value={billDate} onChange={({ detail }) => setBillDate(detail.value)} />
            </FormField>
            <FormField label="Due date">
              <Input type="date" value={dueDate} onChange={({ detail }) => setDueDate(detail.value)} />
            </FormField>
            <FormField label="Bill number">
              <Input value={billNumber} onChange={({ detail }) => setBillNumber(detail.value)} />
            </FormField>
          </ColumnLayout>
          <FormField label="Memo">
            <Input value={memo} onChange={({ detail }) => setMemo(detail.value)} />
          </FormField>

          <FormField label="Expense lines">
            <SpaceBetween size="xs">
              {lines.map((line, idx) => (
                <ColumnLayout key={idx} columns={3}>
                  <Select
                    selectedOption={line.account_id ? accountOptions.find((o) => o.value === line.account_id) ?? null : null}
                    options={accountOptions}
                    onChange={({ detail }) => updateLine(idx, { account_id: detail.selectedOption.value ?? '' })}
                    filteringType="auto"
                    placeholder="Expense account"
                    empty="No accounts"
                  />
                  <Input
                    type="number"
                    value={line.amount}
                    placeholder="Amount"
                    onChange={({ detail }) => updateLine(idx, { amount: detail.value })}
                  />
                  <SpaceBetween direction="horizontal" size="xs">
                    <Input
                      value={line.description}
                      placeholder="Description"
                      onChange={({ detail }) => updateLine(idx, { description: detail.value })}
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
                onClick={() => setLines((prev) => [...prev, { account_id: '', amount: '', description: '' }])}
              >
                Add line
              </Button>
              <Box textAlign="right" fontWeight="bold">Total: {fmt(billTotal)}</Box>
            </SpaceBetween>
          </FormField>
        </SpaceBetween>
      </EntityFormModal>

      {/* Payment modal */}
      <EntityFormModal
        visible={payModalOpen}
        title="Record payment"
        onCancel={() => setPayModalOpen(false)}
        onSubmit={submitPayment}
        submitting={savingPay}
        submitLabel="Record"
      >
        <SpaceBetween size="m">
          <Box>Outstanding balance: <strong>{fmt(payBill?.balance_due)}</strong></Box>
          <FormField label="Payment date">
            <Input type="date" value={payDate} onChange={({ detail }) => setPayDate(detail.value)} />
          </FormField>
          <FormField label="Amount">
            <Input type="number" value={payAmount} onChange={({ detail }) => setPayAmount(detail.value)} />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Method">
              <Input value={payMethod} onChange={({ detail }) => setPayMethod(detail.value)} placeholder="check, ACH…" />
            </FormField>
            <FormField label="Reference">
              <Input value={payReference} onChange={({ detail }) => setPayReference(detail.value)} />
            </FormField>
          </ColumnLayout>
        </SpaceBetween>
      </EntityFormModal>
    </ContentLayout>
  );
};

export default AccountsPayablePage;
