import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Tabs from '@cloudscape-design/components/tabs';
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
import { gl as glApi, leases as leasesApi } from '@/api';
import type {
  GLAccount,
  AccountingPeriod,
  JournalEntry,
  TrialBalanceRow,
} from '@/types';

const ACCOUNT_TYPES = ['asset', 'liability', 'equity', 'revenue', 'expense'];

const fmt = (v: number | null | undefined) =>
  v != null ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

interface LeaseOption { label: string; value: string; }

interface LineDraft { account_id: string; debit: string; credit: string; }

const GeneralLedgerPage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const [accounts, setAccounts] = useState<GLAccount[]>([]);
  const [periods, setPeriods] = useState<AccountingPeriod[]>([]);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [trialBalance, setTrialBalance] = useState<TrialBalanceRow[]>([]);
  const [leaseOptions, setLeaseOptions] = useState<LeaseOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  // Account modal
  const [acctModalOpen, setAcctModalOpen] = useState(false);
  const [acctForm, setAcctForm] = useState({ code: '', name: '', type: 'asset' });
  const [savingAcct, setSavingAcct] = useState(false);

  // Journal entry modal
  const [jeModalOpen, setJeModalOpen] = useState(false);
  const [jeDate, setJeDate] = useState(new Date().toISOString().slice(0, 10));
  const [jeMemo, setJeMemo] = useState('');
  const [jeLines, setJeLines] = useState<LineDraft[]>([
    { account_id: '', debit: '', credit: '' },
    { account_id: '', debit: '', credit: '' },
  ]);
  const [savingJe, setSavingJe] = useState(false);

  // Post-lease modal
  const [postLeaseId, setPostLeaseId] = useState('');
  const [postingLease, setPostingLease] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [acctRes, periodRes, entryRes, tbRes] = await Promise.all([
        glApi.listAccounts(),
        glApi.listPeriods(),
        glApi.listEntries(),
        glApi.trialBalance(),
      ]);
      setAccounts(acctRes.data);
      setPeriods(periodRes.data);
      setEntries(entryRes.data);
      setTrialBalance(tbRes.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load general ledger data.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    leasesApi.list({ page_size: 1000 }).then((res) => {
      setLeaseOptions(res.data.items.map((l) => ({ label: l.lease_name, value: l.id })));
    }).catch(() => {});
  }, []);

  const accountOptions = useMemo(
    () => accounts.map((a) => ({ label: `${a.code} — ${a.name}`, value: a.id })),
    [accounts],
  );

  // ─── Account create ──────────────────────────────────────────────────────────
  const submitAccount = async () => {
    if (!acctForm.code.trim() || !acctForm.name.trim()) {
      addFlash({ type: 'error', content: 'Code and name are required.' });
      return;
    }
    setSavingAcct(true);
    try {
      await glApi.createAccount({ code: acctForm.code.trim(), name: acctForm.name.trim(), type: acctForm.type });
      addFlash({ type: 'success', content: 'Account created.' });
      setAcctModalOpen(false);
      setAcctForm({ code: '', name: '', type: 'asset' });
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to create account.' });
    } finally {
      setSavingAcct(false);
    }
  };

  // ─── Journal entry create ─────────────────────────────────────────────────────
  const jeTotals = useMemo(() => {
    const debit = jeLines.reduce((s, l) => s + (parseFloat(l.debit) || 0), 0);
    const credit = jeLines.reduce((s, l) => s + (parseFloat(l.credit) || 0), 0);
    return { debit, credit, balanced: Math.abs(debit - credit) < 0.005 && debit > 0 };
  }, [jeLines]);

  const updateLine = (idx: number, patch: Partial<LineDraft>) => {
    setJeLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  const submitJournalEntry = async () => {
    const lines = jeLines
      .filter((l) => l.account_id && (parseFloat(l.debit) > 0 || parseFloat(l.credit) > 0))
      .map((l) => ({
        account_id: l.account_id,
        debit: String(parseFloat(l.debit) || 0),
        credit: String(parseFloat(l.credit) || 0),
      }));
    if (lines.length < 2) {
      addFlash({ type: 'error', content: 'A journal entry needs at least two lines.' });
      return;
    }
    if (!jeTotals.balanced) {
      addFlash({ type: 'error', content: 'Debits must equal credits.' });
      return;
    }
    setSavingJe(true);
    try {
      await glApi.createEntry({ entry_date: jeDate, memo: jeMemo || null, lines });
      addFlash({ type: 'success', content: 'Journal entry posted.' });
      setJeModalOpen(false);
      setJeMemo('');
      setJeLines([
        { account_id: '', debit: '', credit: '' },
        { account_id: '', debit: '', credit: '' },
      ]);
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to post journal entry.' });
    } finally {
      setSavingJe(false);
    }
  };

  // ─── Period close / reopen ────────────────────────────────────────────────────
  const togglePeriod = async (p: AccountingPeriod) => {
    try {
      if (p.status === 'closed') {
        await glApi.reopenPeriod(p.year, p.month);
        addFlash({ type: 'success', content: `Reopened ${p.year}-${String(p.month).padStart(2, '0')}.` });
      } else {
        await glApi.closePeriod(p.year, p.month);
        addFlash({ type: 'success', content: `Closed ${p.year}-${String(p.month).padStart(2, '0')}.` });
      }
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to update period.' });
    }
  };

  // ─── Post lease ───────────────────────────────────────────────────────────────
  const postLease = async () => {
    if (!postLeaseId) return;
    setPostingLease(true);
    try {
      const res = await glApi.postLease(postLeaseId);
      addFlash({ type: 'success', content: `Posted ${res.data.length} journal entries from lease.` });
      setPostLeaseId('');
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to post lease entries.' });
    } finally {
      setPostingLease(false);
    }
  };

  // ─── Export ───────────────────────────────────────────────────────────────────
  const exportCsv = async () => {
    setExporting(true);
    try {
      const res = await glApi.exportCsv();
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `general_journal_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      addFlash({ type: 'error', content: 'Failed to export journal.' });
    } finally {
      setExporting(false);
    }
  };

  const tbTotals = useMemo(() => ({
    debit: trialBalance.reduce((s, r) => s + Number(r.debit), 0),
    credit: trialBalance.reduce((s, r) => s + Number(r.credit), 0),
  }), [trialBalance]);

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Audit-grade double-entry general ledger: chart of accounts, journal entries, period close, and QuickBooks-compatible export."
          actions={
            <Button iconName="download" onClick={exportCsv} loading={exporting}>
              Export journal (CSV)
            </Button>
          }
        >
          General Ledger
        </Header>
      }
    >
      <Tabs
        tabs={[
          {
            id: 'accounts',
            label: 'Chart of Accounts',
            content: (
              <Container
                header={
                  <Header
                    variant="h2"
                    actions={<Button onClick={() => setAcctModalOpen(true)}>Add account</Button>}
                  >
                    Chart of Accounts
                  </Header>
                }
              >
                <Table
                  loading={loading}
                  items={accounts}
                  columnDefinitions={[
                    { id: 'code', header: 'Code', cell: (a) => a.code, sortingField: 'code' },
                    { id: 'name', header: 'Name', cell: (a) => a.name },
                    { id: 'type', header: 'Type', cell: (a) => <Badge>{a.type}</Badge> },
                    { id: 'normal', header: 'Normal balance', cell: (a) => a.normal_balance },
                    { id: 'active', header: 'Active', cell: (a) => (a.is_active ? 'Yes' : 'No') },
                  ]}
                  empty={<Box textAlign="center" color="inherit">No accounts yet.</Box>}
                />
              </Container>
            ),
          },
          {
            id: 'entries',
            label: 'Journal Entries',
            content: (
              <Container
                header={
                  <Header
                    variant="h2"
                    actions={
                      <SpaceBetween direction="horizontal" size="xs">
                        <Select
                          placeholder="Post lease to GL…"
                          selectedOption={
                            postLeaseId
                              ? leaseOptions.find((o) => o.value === postLeaseId) ?? null
                              : null
                          }
                          options={leaseOptions}
                          onChange={({ detail }) => setPostLeaseId(detail.selectedOption.value ?? '')}
                          filteringType="auto"
                          empty="No leases"
                        />
                        <Button onClick={postLease} disabled={!postLeaseId} loading={postingLease}>
                          Post lease
                        </Button>
                        <Button variant="primary" onClick={() => setJeModalOpen(true)}>
                          New entry
                        </Button>
                      </SpaceBetween>
                    }
                  >
                    Journal Entries
                  </Header>
                }
              >
                <Table
                  loading={loading}
                  items={entries}
                  columnDefinitions={[
                    { id: 'date', header: 'Date', cell: (e) => e.entry_date },
                    { id: 'memo', header: 'Memo', cell: (e) => e.memo || '—' },
                    { id: 'source', header: 'Source', cell: (e) => <Badge color={e.source === 'lease' ? 'blue' : 'grey'}>{e.source}</Badge> },
                    {
                      id: 'lines',
                      header: 'Lines',
                      cell: (e) => (
                        <SpaceBetween size="xxs">
                          {e.lines.map((l) => (
                            <Box key={l.id} fontSize="body-s">
                              {l.account_code} {l.account_name}:{' '}
                              {Number(l.debit) > 0 ? `Dr ${fmt(l.debit)}` : `Cr ${fmt(l.credit)}`}
                            </Box>
                          ))}
                        </SpaceBetween>
                      ),
                    },
                    { id: 'status', header: 'Status', cell: (e) => <Badge color="green">{e.status}</Badge> },
                  ]}
                  empty={<Box textAlign="center" color="inherit">No journal entries yet.</Box>}
                />
              </Container>
            ),
          },
          {
            id: 'periods',
            label: 'Periods',
            content: (
              <Container header={<Header variant="h2">Accounting Periods</Header>}>
                <Table
                  loading={loading}
                  items={periods}
                  columnDefinitions={[
                    { id: 'period', header: 'Period', cell: (p) => `${MONTHS[p.month - 1]} ${p.year}` },
                    { id: 'status', header: 'Status', cell: (p) => <Badge color={p.status === 'closed' ? 'red' : 'green'}>{p.status}</Badge> },
                    { id: 'closed_at', header: 'Closed at', cell: (p) => (p.closed_at ? new Date(p.closed_at).toLocaleString() : '—') },
                    {
                      id: 'actions',
                      header: 'Actions',
                      cell: (p) => (
                        <Button variant="inline-link" onClick={() => togglePeriod(p)}>
                          {p.status === 'closed' ? 'Reopen' : 'Close'}
                        </Button>
                      ),
                    },
                  ]}
                  empty={<Box textAlign="center" color="inherit">No periods yet. Periods are created when entries are posted.</Box>}
                />
              </Container>
            ),
          },
          {
            id: 'trial-balance',
            label: 'Trial Balance',
            content: (
              <Container header={<Header variant="h2">Trial Balance</Header>}>
                <Table
                  loading={loading}
                  items={trialBalance}
                  columnDefinitions={[
                    { id: 'code', header: 'Code', cell: (r) => r.code },
                    { id: 'name', header: 'Account', cell: (r) => r.name },
                    { id: 'type', header: 'Type', cell: (r) => r.type },
                    { id: 'debit', header: 'Debit', cell: (r) => fmt(r.debit) },
                    { id: 'credit', header: 'Credit', cell: (r) => fmt(r.credit) },
                    { id: 'balance', header: 'Balance', cell: (r) => `${fmt(r.balance)} ${r.balance_side === 'debit' ? 'Dr' : 'Cr'}` },
                  ]}
                  footer={
                    <ColumnLayout columns={3} variant="text-grid">
                      <Box><strong>Totals</strong></Box>
                      <Box>Debit: <strong>{fmt(tbTotals.debit)}</strong></Box>
                      <Box>Credit: <strong>{fmt(tbTotals.credit)}</strong>{' '}
                        {Math.abs(tbTotals.debit - tbTotals.credit) < 0.005
                          ? <Badge color="green">Balanced</Badge>
                          : <Badge color="red">Out of balance</Badge>}
                      </Box>
                    </ColumnLayout>
                  }
                  empty={<Box textAlign="center" color="inherit">No postings yet.</Box>}
                />
              </Container>
            ),
          },
        ]}
      />

      {/* Account create modal */}
      <Modal
        visible={acctModalOpen}
        onDismiss={() => setAcctModalOpen(false)}
        header="Add account"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setAcctModalOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={submitAccount} loading={savingAcct}>Create</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Code">
            <Input value={acctForm.code} onChange={({ detail }) => setAcctForm((f) => ({ ...f, code: detail.value }))} placeholder="e.g. 6300" />
          </FormField>
          <FormField label="Name">
            <Input value={acctForm.name} onChange={({ detail }) => setAcctForm((f) => ({ ...f, name: detail.value }))} placeholder="e.g. Utilities Expense" />
          </FormField>
          <FormField label="Type">
            <Select
              selectedOption={{ label: acctForm.type, value: acctForm.type }}
              options={ACCOUNT_TYPES.map((t) => ({ label: t, value: t }))}
              onChange={({ detail }) => setAcctForm((f) => ({ ...f, type: detail.selectedOption.value ?? 'asset' }))}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Journal entry modal */}
      <Modal
        visible={jeModalOpen}
        onDismiss={() => setJeModalOpen(false)}
        header="New journal entry"
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setJeModalOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={submitJournalEntry} loading={savingJe} disabled={!jeTotals.balanced}>
                Post entry
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <ColumnLayout columns={2}>
            <FormField label="Date">
              <Input type="date" value={jeDate} onChange={({ detail }) => setJeDate(detail.value)} />
            </FormField>
            <FormField label="Memo">
              <Input value={jeMemo} onChange={({ detail }) => setJeMemo(detail.value)} placeholder="Optional" />
            </FormField>
          </ColumnLayout>

          {jeLines.map((line, idx) => (
            <ColumnLayout key={idx} columns={3}>
              <FormField label={idx === 0 ? 'Account' : ''}>
                <Select
                  selectedOption={line.account_id ? accountOptions.find((o) => o.value === line.account_id) ?? null : null}
                  options={accountOptions}
                  onChange={({ detail }) => updateLine(idx, { account_id: detail.selectedOption.value ?? '' })}
                  filteringType="auto"
                  placeholder="Select account"
                />
              </FormField>
              <FormField label={idx === 0 ? 'Debit' : ''}>
                <Input type="number" value={line.debit} onChange={({ detail }) => updateLine(idx, { debit: detail.value, credit: '' })} placeholder="0.00" />
              </FormField>
              <FormField label={idx === 0 ? 'Credit' : ''}>
                <Input type="number" value={line.credit} onChange={({ detail }) => updateLine(idx, { credit: detail.value, debit: '' })} placeholder="0.00" />
              </FormField>
            </ColumnLayout>
          ))}

          <Button onClick={() => setJeLines((prev) => [...prev, { account_id: '', debit: '', credit: '' }])}>
            Add line
          </Button>

          <ColumnLayout columns={3} variant="text-grid">
            <Box>Total debit: <strong>{fmt(jeTotals.debit)}</strong></Box>
            <Box>Total credit: <strong>{fmt(jeTotals.credit)}</strong></Box>
            <Box>
              {jeTotals.balanced
                ? <Badge color="green">Balanced</Badge>
                : <Badge color="red">Unbalanced</Badge>}
            </Box>
          </ColumnLayout>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default GeneralLedgerPage;
