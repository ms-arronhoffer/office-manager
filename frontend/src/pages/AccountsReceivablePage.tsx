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
import { ar as arApi, gl as glApi } from '@/api';
import type { CustomerInvoice, Customer, ArAgingReport, GLAccount } from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const today = () => new Date().toISOString().slice(0, 10);

const BUCKET_LABELS: Record<string, string> = {
  current: 'Current',
  '1_30': '1–30',
  '31_60': '31–60',
  '61_90': '61–90',
  '90_plus': '90+',
};

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

const AccountsReceivablePage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const [invoices, setInvoices] = useState<CustomerInvoice[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [accounts, setAccounts] = useState<GLAccount[]>([]);
  const [aging, setAging] = useState<ArAgingReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<CustomerInvoice | null>(null);

  // Invoice modal
  const [invModalOpen, setInvModalOpen] = useState(false);
  const [customerId, setCustomerId] = useState('');
  const [invoiceDate, setInvoiceDate] = useState(today());
  const [dueDate, setDueDate] = useState('');
  const [invoiceNumber, setInvoiceNumber] = useState('');
  const [memo, setMemo] = useState('');
  const [lines, setLines] = useState<LineDraft[]>([{ account_id: '', amount: '', description: '' }]);
  const [savingInv, setSavingInv] = useState(false);

  // Receipt modal
  const [rcptModalOpen, setRcptModalOpen] = useState(false);
  const [rcptInvoice, setRcptInvoice] = useState<CustomerInvoice | null>(null);
  const [rcptDate, setRcptDate] = useState(today());
  const [rcptAmount, setRcptAmount] = useState('');
  const [rcptMethod, setRcptMethod] = useState('');
  const [rcptReference, setRcptReference] = useState('');
  const [savingRcpt, setSavingRcpt] = useState(false);

  // Customer modal
  const [custModalOpen, setCustModalOpen] = useState(false);
  const [custName, setCustName] = useState('');
  const [custEmail, setCustEmail] = useState('');
  const [savingCust, setSavingCust] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [inv, agingRes] = await Promise.all([
        arApi.listInvoices(),
        arApi.aging(),
      ]);
      setInvoices(inv.data);
      setAging(agingRes.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load invoices.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  const loadCustomers = useCallback(async () => {
    try {
      const res = await arApi.listCustomers();
      setCustomers(res.data);
    } catch {
      /* non-fatal */
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    loadCustomers();
    glApi.listAccounts().then((res) => setAccounts(res.data)).catch(() => {});
  }, [loadCustomers]);

  const customerOpts = useMemo<Opt[]>(
    () => customers.map((c) => ({ label: c.name, value: c.id })),
    [customers],
  );
  const accountOptions = useMemo<Opt[]>(
    () =>
      accounts
        .filter((a) => a.is_active && a.type === 'revenue')
        .map((a) => ({ label: `${a.code} — ${a.name}`, value: a.id })),
    [accounts],
  );
  const accountLabel = useCallback(
    (id: string) => {
      const acct = accounts.find((a) => a.id === id);
      return acct ? `${acct.code} — ${acct.name}` : id;
    },
    [accounts],
  );
  const customerLabel = useCallback(
    (id: string) => customerOpts.find((o) => o.value === id)?.label ?? id,
    [customerOpts],
  );

  const resetInvoiceForm = () => {
    setCustomerId('');
    setInvoiceDate(today());
    setDueDate('');
    setInvoiceNumber('');
    setMemo('');
    setLines([{ account_id: '', amount: '', description: '' }]);
  };

  const updateLine = (idx: number, patch: Partial<LineDraft>) =>
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  const invoiceTotal = useMemo(
    () => lines.reduce((s, l) => s + (parseFloat(l.amount) || 0), 0),
    [lines],
  );

  const submitInvoice = async () => {
    const cleanLines = lines
      .filter((l) => l.account_id && parseFloat(l.amount) > 0)
      .map((l) => ({
        account_id: l.account_id,
        amount: parseFloat(l.amount),
        description: l.description || null,
      }));
    if (!customerId) {
      addFlash({ type: 'error', content: 'A customer is required.' });
      return;
    }
    if (cleanLines.length === 0) {
      addFlash({ type: 'error', content: 'Add at least one revenue line with an account and amount.' });
      return;
    }
    setSavingInv(true);
    try {
      await arApi.createInvoice({
        customer_id: customerId,
        invoice_date: invoiceDate,
        due_date: dueDate || null,
        invoice_number: invoiceNumber || null,
        memo: memo || null,
        lines: cleanLines,
      });
      addFlash({ type: 'success', content: 'Invoice created.' });
      setInvModalOpen(false);
      resetInvoiceForm();
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to create invoice.' });
    } finally {
      setSavingInv(false);
    }
  };

  const submitCustomer = async () => {
    if (!custName.trim()) {
      addFlash({ type: 'error', content: 'A customer name is required.' });
      return;
    }
    setSavingCust(true);
    try {
      const res = await arApi.createCustomer({ name: custName, contact_email: custEmail || null });
      addFlash({ type: 'success', content: 'Customer created.' });
      setCustModalOpen(false);
      setCustName('');
      setCustEmail('');
      await loadCustomers();
      setCustomerId(res.data.id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to create customer.' });
    } finally {
      setSavingCust(false);
    }
  };

  const refreshSelected = (updated: CustomerInvoice) => {
    setInvoices((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    setSelected((prev) => (prev && prev.id === updated.id ? updated : prev));
  };

  const runAction = async (label: string, fn: () => Promise<{ data: CustomerInvoice }>) => {
    try {
      const res = await fn();
      refreshSelected(res.data);
      addFlash({ type: 'success', content: label });
      // Aging depends on finalized/paid state; refresh it.
      arApi.aging().then((r) => setAging(r.data)).catch(() => {});
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Action failed.' });
    }
  };

  const finalizeInvoice = (i: CustomerInvoice) =>
    runAction('Invoice finalized and posted to GL.', () => arApi.finalizeInvoice(i.id));

  const voidInvoice = (i: CustomerInvoice) =>
    runAction('Invoice voided.', () => arApi.voidInvoice(i.id));

  const deleteInvoice = async (i: CustomerInvoice) => {
    try {
      await arApi.deleteInvoice(i.id);
      addFlash({ type: 'success', content: 'Invoice deleted.' });
      setSelected(null);
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to delete invoice.' });
    }
  };

  const openReceipt = (i: CustomerInvoice) => {
    setRcptInvoice(i);
    setRcptDate(today());
    setRcptAmount(String(i.balance_due));
    setRcptMethod('');
    setRcptReference('');
    setRcptModalOpen(true);
  };

  const submitReceipt = async () => {
    if (!rcptInvoice) return;
    const amount = parseFloat(rcptAmount);
    if (!(amount > 0)) {
      addFlash({ type: 'error', content: 'Receipt amount must be greater than zero.' });
      return;
    }
    setSavingRcpt(true);
    try {
      const res = await arApi.createReceipt(rcptInvoice.id, {
        receipt_date: rcptDate,
        amount,
        method: rcptMethod || null,
        reference: rcptReference || null,
      });
      refreshSelected(res.data);
      addFlash({ type: 'success', content: 'Receipt recorded.' });
      setRcptModalOpen(false);
      arApi.aging().then((r) => setAging(r.data)).catch(() => {});
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to record receipt.' });
    } finally {
      setSavingRcpt(false);
    }
  };

  const deleteReceipt = (receiptId: string) =>
    runAction('Receipt removed.', () => arApi.deleteReceipt(receiptId));

  const agingBuckets = aging?.buckets ?? [];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Customer invoices and receipts posting to the audit-grade general ledger."
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setCustModalOpen(true)}>New customer</Button>
              <Button variant="primary" onClick={() => setInvModalOpen(true)}>New invoice</Button>
            </SpaceBetween>
          }
        >
          Accounts Receivable
        </Header>
      }
    >
      <SpaceBetween size="l">
        {aging && (
          <Container header={<Header variant="h2" description={`As of ${aging.as_of}`}>AR aging</Header>}>
            <Table
              variant="embedded"
              items={aging.customers}
              columnDefinitions={[
                { id: 'customer', header: 'Customer', cell: (c) => c.customer_name || '—' },
                ...agingBuckets.map((b) => ({
                  id: b,
                  header: BUCKET_LABELS[b] ?? b,
                  cell: (c: ArAgingReport['customers'][number]) => (
                    <Box textAlign="right">{fmt(c.buckets[b])}</Box>
                  ),
                })),
                { id: 'total', header: 'Total', cell: (c) => <Box textAlign="right"><strong>{fmt(c.total)}</strong></Box> },
              ]}
              empty={<Box textAlign="center" color="inherit">No open receivables.</Box>}
              footer={
                <ColumnLayout columns={agingBuckets.length + 2} variant="text-grid">
                  <Box fontWeight="bold">Totals</Box>
                  {agingBuckets.map((b) => (
                    <Box key={b} textAlign="right">{fmt(aging.totals[b])}</Box>
                  ))}
                  <Box textAlign="right" fontWeight="bold">{fmt(aging.grand_total)}</Box>
                </ColumnLayout>
              }
            />
          </Container>
        )}

        <Table
          loading={loading}
          items={invoices}
          selectionType="single"
          selectedItems={selected ? [selected] : []}
          onSelectionChange={({ detail }) => setSelected(detail.selectedItems[0] ?? null)}
          trackBy="id"
          header={<Header variant="h2" counter={`(${invoices.length})`}>Invoices</Header>}
          columnDefinitions={[
            { id: 'customer', header: 'Customer', cell: (i) => customerLabel(i.customer_id) },
            { id: 'number', header: 'Invoice #', cell: (i) => i.invoice_number || '—' },
            { id: 'date', header: 'Invoice date', cell: (i) => i.invoice_date },
            { id: 'due', header: 'Due', cell: (i) => i.due_date || '—' },
            { id: 'total', header: 'Total', cell: (i) => <Box textAlign="right">{fmt(i.total_amount)}</Box> },
            { id: 'received', header: 'Received', cell: (i) => <Box textAlign="right">{fmt(i.amount_received)}</Box> },
            { id: 'balance', header: 'Balance', cell: (i) => <Box textAlign="right">{fmt(i.balance_due)}</Box> },
            { id: 'rcptstate', header: 'Receipt', cell: (i) => stateBadge(i.receipt_state) },
            { id: 'status', header: 'Status', cell: (i) => statusBadge(i.status) },
          ]}
          empty={<Box textAlign="center" color="inherit">No invoices yet.</Box>}
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
                        <Button onClick={() => deleteInvoice(selected)}>Delete</Button>
                        <Button variant="primary" onClick={() => finalizeInvoice(selected)}>Finalize &amp; post</Button>
                      </>
                    )}
                    {selected.status === 'finalized' && (
                      <>
                        {selected.balance_due > 0 && (
                          <Button variant="primary" onClick={() => openReceipt(selected)}>Record receipt</Button>
                        )}
                        {selected.amount_received === 0 && (
                          <Button onClick={() => voidInvoice(selected)}>Void</Button>
                        )}
                      </>
                    )}
                  </SpaceBetween>
                }
              >
                Invoice — {customerLabel(selected.customer_id)}
              </Header>
            }
          >
            <SpaceBetween size="m">
              <ColumnLayout columns={4} variant="text-grid">
                <div><Box variant="awsui-key-label">Total</Box>{fmt(selected.total_amount)}</div>
                <div><Box variant="awsui-key-label">Received</Box>{fmt(selected.amount_received)}</div>
                <div><Box variant="awsui-key-label">Balance</Box>{fmt(selected.balance_due)}</div>
                <div><Box variant="awsui-key-label">Status</Box>{statusBadge(selected.status)}</div>
              </ColumnLayout>
              {selected.source && (
                <Box variant="small">Source: {selected.source}</Box>
              )}

              <Table
                variant="embedded"
                header={<Header variant="h3">Revenue lines</Header>}
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
                header={<Header variant="h3">Receipts</Header>}
                items={selected.receipts}
                columnDefinitions={[
                  { id: 'date', header: 'Date', cell: (r) => r.receipt_date },
                  { id: 'amount', header: 'Amount', cell: (r) => <Box textAlign="right">{fmt(r.amount)}</Box> },
                  { id: 'method', header: 'Method', cell: (r) => r.method || '—' },
                  { id: 'reference', header: 'Reference', cell: (r) => r.reference || '—' },
                  {
                    id: 'actions',
                    header: '',
                    cell: (r) => <Button variant="inline-link" onClick={() => deleteReceipt(r.id)}>Remove</Button>,
                  },
                ]}
                empty={<Box textAlign="center" color="inherit">No receipts recorded.</Box>}
              />
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>

      {/* New invoice modal */}
      <Modal
        visible={invModalOpen}
        onDismiss={() => setInvModalOpen(false)}
        header="New customer invoice"
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setInvModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingInv} onClick={submitInvoice}>Create</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Customer">
            <SpaceBetween direction="horizontal" size="xs">
              <Select
                selectedOption={customerId ? customerOpts.find((o) => o.value === customerId) ?? null : null}
                options={customerOpts}
                onChange={({ detail }) => setCustomerId(detail.selectedOption.value ?? '')}
                filteringType="auto"
                placeholder="Select a customer"
                empty="No customers"
              />
              <Button onClick={() => setCustModalOpen(true)}>New</Button>
            </SpaceBetween>
          </FormField>
          <ColumnLayout columns={3}>
            <FormField label="Invoice date">
              <Input type="date" value={invoiceDate} onChange={({ detail }) => setInvoiceDate(detail.value)} />
            </FormField>
            <FormField label="Due date">
              <Input type="date" value={dueDate} onChange={({ detail }) => setDueDate(detail.value)} />
            </FormField>
            <FormField label="Invoice number">
              <Input value={invoiceNumber} onChange={({ detail }) => setInvoiceNumber(detail.value)} />
            </FormField>
          </ColumnLayout>
          <FormField label="Memo">
            <Input value={memo} onChange={({ detail }) => setMemo(detail.value)} />
          </FormField>

          <FormField label="Revenue lines">
            <SpaceBetween size="xs">
              {lines.map((line, idx) => (
                <ColumnLayout key={idx} columns={3}>
                  <Select
                    selectedOption={line.account_id ? accountOptions.find((o) => o.value === line.account_id) ?? null : null}
                    options={accountOptions}
                    onChange={({ detail }) => updateLine(idx, { account_id: detail.selectedOption.value ?? '' })}
                    filteringType="auto"
                    placeholder="Revenue account"
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
              <Box textAlign="right" fontWeight="bold">Total: {fmt(invoiceTotal)}</Box>
            </SpaceBetween>
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Receipt modal */}
      <Modal
        visible={rcptModalOpen}
        onDismiss={() => setRcptModalOpen(false)}
        header="Record receipt"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setRcptModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingRcpt} onClick={submitReceipt}>Record</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box>Outstanding balance: <strong>{fmt(rcptInvoice?.balance_due)}</strong></Box>
          <FormField label="Receipt date">
            <Input type="date" value={rcptDate} onChange={({ detail }) => setRcptDate(detail.value)} />
          </FormField>
          <FormField label="Amount">
            <Input type="number" value={rcptAmount} onChange={({ detail }) => setRcptAmount(detail.value)} />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Method">
              <Input value={rcptMethod} onChange={({ detail }) => setRcptMethod(detail.value)} placeholder="check, ACH…" />
            </FormField>
            <FormField label="Reference">
              <Input value={rcptReference} onChange={({ detail }) => setRcptReference(detail.value)} />
            </FormField>
          </ColumnLayout>
        </SpaceBetween>
      </Modal>

      {/* New customer modal */}
      <Modal
        visible={custModalOpen}
        onDismiss={() => setCustModalOpen(false)}
        header="New customer"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setCustModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingCust} onClick={submitCustomer}>Create</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Name">
            <Input value={custName} onChange={({ detail }) => setCustName(detail.value)} />
          </FormField>
          <FormField label="Billing email">
            <Input value={custEmail} onChange={({ detail }) => setCustEmail(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default AccountsReceivablePage;
