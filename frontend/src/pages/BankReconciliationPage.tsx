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
import FileUpload from '@cloudscape-design/components/file-upload';
import Checkbox from '@cloudscape-design/components/checkbox';
import { useFlashbar } from '@/context/FlashbarContext';
import { bank as bankApi, gl as glApi } from '@/api';
import type {
  BankAccount,
  BankTransaction,
  BankReconciliation,
  ReconciliationReport,
  GLAccount,
} from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const today = () => new Date().toISOString().slice(0, 10);

interface Opt { label: string; value: string; }

const statusBadge = (s: string) => {
  const color = s === 'completed' ? 'green' : s === 'in_progress' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s.replace('_', ' ')}</Badge>;
};

const txnStatusBadge = (s: string) => {
  const color = s === 'cleared' ? 'green' : 'grey';
  return <Badge color={color as 'green' | 'grey'}>{s}</Badge>;
};

const BankReconciliationPage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [glAccounts, setGlAccounts] = useState<GLAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState('');
  const [transactions, setTransactions] = useState<BankTransaction[]>([]);
  const [reconciliations, setReconciliations] = useState<BankReconciliation[]>([]);
  const [report, setReport] = useState<ReconciliationReport | null>(null);
  const [loading, setLoading] = useState(true);

  // Account modal
  const [acctModalOpen, setAcctModalOpen] = useState(false);
  const [acctName, setAcctName] = useState('');
  const [acctGlId, setAcctGlId] = useState('');
  const [acctInstitution, setAcctInstitution] = useState('');
  const [acctLast4, setAcctLast4] = useState('');
  const [savingAcct, setSavingAcct] = useState(false);

  // Import
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importing, setImporting] = useState(false);

  // Manual transaction modal
  const [txnModalOpen, setTxnModalOpen] = useState(false);
  const [txnDate, setTxnDate] = useState(today());
  const [txnAmount, setTxnAmount] = useState('');
  const [txnDescription, setTxnDescription] = useState('');
  const [txnReference, setTxnReference] = useState('');
  const [savingTxn, setSavingTxn] = useState(false);

  // Reconciliation modal
  const [reconModalOpen, setReconModalOpen] = useState(false);
  const [stmtDate, setStmtDate] = useState(today());
  const [endingBalance, setEndingBalance] = useState('');
  const [beginningBalance, setBeginningBalance] = useState('');
  const [savingRecon, setSavingRecon] = useState(false);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const res = await bankApi.listAccounts();
      setAccounts(res.data);
      setSelectedAccountId((prev) => prev || res.data[0]?.id || '');
    } catch {
      addFlash({ type: 'error', content: 'Failed to load bank accounts.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  const loadAccountData = useCallback(
    async (accountId: string) => {
      if (!accountId) {
        setTransactions([]);
        setReconciliations([]);
        return;
      }
      try {
        const [txns, recons] = await Promise.all([
          bankApi.listTransactions(accountId),
          bankApi.listReconciliations(accountId),
        ]);
        setTransactions(txns.data);
        setReconciliations(recons.data);
      } catch {
        addFlash({ type: 'error', content: 'Failed to load account activity.' });
      }
    },
    [addFlash],
  );

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  useEffect(() => {
    glApi.listAccounts().then((res) => setGlAccounts(res.data)).catch(() => {});
  }, []);

  useEffect(() => {
    setReport(null);
    loadAccountData(selectedAccountId);
  }, [selectedAccountId, loadAccountData]);

  const accountOpts = useMemo<Opt[]>(
    () => accounts.map((a) => ({ label: `${a.name}${a.is_active ? '' : ' (inactive)'}`, value: a.id })),
    [accounts],
  );
  const cashAccountOpts = useMemo<Opt[]>(
    () =>
      glAccounts
        .filter((a) => a.is_active && a.type === 'asset')
        .map((a) => ({ label: `${a.code} — ${a.name}`, value: a.id })),
    [glAccounts],
  );
  const selectedAccount = useMemo(
    () => accounts.find((a) => a.id === selectedAccountId) ?? null,
    [accounts, selectedAccountId],
  );

  // ─── Account ───────────────────────────────────────────────────────────────
  const submitAccount = async () => {
    if (!acctName.trim()) {
      addFlash({ type: 'error', content: 'An account name is required.' });
      return;
    }
    if (!acctGlId) {
      addFlash({ type: 'error', content: 'Select the GL cash (asset) account to map to.' });
      return;
    }
    setSavingAcct(true);
    try {
      const res = await bankApi.createAccount({
        name: acctName,
        gl_account_id: acctGlId,
        institution: acctInstitution || null,
        account_number_last4: acctLast4 || null,
      });
      addFlash({ type: 'success', content: 'Bank account created.' });
      setAcctModalOpen(false);
      setAcctName('');
      setAcctGlId('');
      setAcctInstitution('');
      setAcctLast4('');
      await loadAccounts();
      setSelectedAccountId(res.data.id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to create bank account.' });
    } finally {
      setSavingAcct(false);
    }
  };

  // ─── Import ──────────────────────────────────────────────────────────────────
  const runImport = async () => {
    if (!selectedAccountId || importFiles.length === 0) return;
    setImporting(true);
    try {
      const res = await bankApi.importStatement(selectedAccountId, importFiles[0]);
      const { imported, skipped, total } = res.data;
      addFlash({
        type: 'success',
        content: `Imported ${imported} of ${total} transactions (${skipped} duplicate${skipped === 1 ? '' : 's'} skipped).`,
      });
      setImportFiles([]);
      await loadAccountData(selectedAccountId);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to import statement.' });
    } finally {
      setImporting(false);
    }
  };

  // ─── Manual transaction ──────────────────────────────────────────────────────
  const submitTransaction = async () => {
    const amount = parseFloat(txnAmount);
    if (!amount) {
      addFlash({ type: 'error', content: 'Enter a non-zero amount (negative for withdrawals).' });
      return;
    }
    setSavingTxn(true);
    try {
      await bankApi.createTransaction(selectedAccountId, {
        txn_date: txnDate,
        amount,
        description: txnDescription || null,
        reference: txnReference || null,
      });
      addFlash({ type: 'success', content: 'Transaction added.' });
      setTxnModalOpen(false);
      setTxnDate(today());
      setTxnAmount('');
      setTxnDescription('');
      setTxnReference('');
      await loadAccountData(selectedAccountId);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to add transaction.' });
    } finally {
      setSavingTxn(false);
    }
  };

  const deleteTransaction = async (txn: BankTransaction) => {
    try {
      await bankApi.deleteTransaction(txn.id);
      addFlash({ type: 'success', content: 'Transaction deleted.' });
      await loadAccountData(selectedAccountId);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to delete transaction.' });
    }
  };

  // ─── Reconciliation ──────────────────────────────────────────────────────────
  const submitReconciliation = async () => {
    const ending = parseFloat(endingBalance);
    if (Number.isNaN(ending)) {
      addFlash({ type: 'error', content: 'Enter the statement ending balance.' });
      return;
    }
    setSavingRecon(true);
    try {
      const res = await bankApi.createReconciliation(selectedAccountId, {
        statement_date: stmtDate,
        ending_balance: ending,
        beginning_balance: beginningBalance === '' ? null : parseFloat(beginningBalance),
      });
      addFlash({ type: 'success', content: 'Reconciliation started.' });
      setReconModalOpen(false);
      setStmtDate(today());
      setEndingBalance('');
      setBeginningBalance('');
      await loadAccountData(selectedAccountId);
      await openReport(res.data.id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to start reconciliation.' });
    } finally {
      setSavingRecon(false);
    }
  };

  const openReport = useCallback(
    async (reconciliationId: string) => {
      try {
        const res = await bankApi.getReconciliationReport(reconciliationId);
        setReport(res.data);
      } catch {
        addFlash({ type: 'error', content: 'Failed to load reconciliation.' });
      }
    },
    [addFlash],
  );

  const refreshReport = useCallback(async () => {
    if (report) await openReport(report.reconciliation.id);
  }, [report, openReport]);

  const toggleCleared = async (txn: BankTransaction, cleared: boolean) => {
    if (!report) return;
    try {
      if (cleared) {
        await bankApi.clear(report.reconciliation.id, [txn.id]);
      } else {
        await bankApi.unclear(report.reconciliation.id, [txn.id]);
      }
      await refreshReport();
      await loadAccountData(selectedAccountId);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to update transaction.' });
    }
  };

  const completeReconciliation = async () => {
    if (!report) return;
    try {
      await bankApi.complete(report.reconciliation.id);
      addFlash({ type: 'success', content: 'Reconciliation completed.' });
      await refreshReport();
      await loadAccountData(selectedAccountId);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to complete reconciliation.' });
    }
  };

  const reopenReconciliation = async () => {
    if (!report) return;
    try {
      await bankApi.reopen(report.reconciliation.id);
      addFlash({ type: 'success', content: 'Reconciliation reopened.' });
      await refreshReport();
      await loadAccountData(selectedAccountId);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Failed to reopen reconciliation.' });
    }
  };

  const isInProgress = report?.reconciliation.status === 'in_progress';
  const summary = report?.reconciliation.summary;

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Register bank accounts, import statements, and reconcile against the general ledger."
          actions={
            <Button variant="primary" onClick={() => setAcctModalOpen(true)}>
              New bank account
            </Button>
          }
        >
          Bank Reconciliation
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Account</Header>}>
          <SpaceBetween size="m">
            <FormField label="Bank account">
              <Select
                selectedOption={accountOpts.find((o) => o.value === selectedAccountId) ?? null}
                onChange={({ detail }) => setSelectedAccountId(detail.selectedOption?.value ?? '')}
                options={accountOpts}
                placeholder={loading ? 'Loading…' : 'Select a bank account'}
                empty="No bank accounts yet"
              />
            </FormField>
            {selectedAccount && (
              <ColumnLayout columns={3} variant="text-grid">
                <div>
                  <Box variant="awsui-key-label">GL cash account</Box>
                  <div>
                    {selectedAccount.gl_account_code
                      ? `${selectedAccount.gl_account_code} — ${selectedAccount.gl_account_name}`
                      : '—'}
                  </div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Institution</Box>
                  <div>{selectedAccount.institution || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Account ending</Box>
                  <div>{selectedAccount.account_number_last4 ? `••••${selectedAccount.account_number_last4}` : '—'}</div>
                </div>
              </ColumnLayout>
            )}
          </SpaceBetween>
        </Container>

        {selectedAccount && (
          <Container header={<Header variant="h2">Import statement</Header>}>
            <SpaceBetween size="m">
              <FileUpload
                onChange={({ detail }) => setImportFiles(detail.value)}
                value={importFiles}
                accept=".csv,.ofx,.qfx,.txt"
                i18nStrings={{
                  uploadButtonText: () => 'Choose statement',
                  dropzoneText: () => 'Drop a CSV or OFX/QFX statement here',
                  removeFileAriaLabel: (i) => `Remove file ${i + 1}`,
                  limitShowFewer: 'Show fewer',
                  limitShowMore: 'Show more',
                  errorIconAriaLabel: 'Error',
                }}
                constraintText="CSV (date, amount/description) or OFX/QFX. Duplicate transactions are skipped automatically."
              />
              <Button onClick={runImport} loading={importing} disabled={importFiles.length === 0}>
                Import transactions
              </Button>
            </SpaceBetween>
          </Container>
        )}

        {selectedAccount && (
          <Table<BankTransaction>
            header={
              <Header
                variant="h2"
                counter={`(${transactions.length})`}
                actions={
                  <Button onClick={() => setTxnModalOpen(true)}>Add transaction</Button>
                }
              >
                Register
              </Header>
            }
            items={transactions}
            loading={loading}
            variant="container"
            empty={<Box textAlign="center" color="inherit">No transactions yet.</Box>}
            columnDefinitions={[
              { id: 'date', header: 'Date', cell: (t) => t.txn_date },
              { id: 'description', header: 'Description', cell: (t) => t.description || '—' },
              { id: 'reference', header: 'Reference', cell: (t) => t.reference || '—' },
              {
                id: 'amount',
                header: 'Amount',
                cell: (t) => (
                  <Box textAlign="right" color={t.amount < 0 ? 'text-status-error' : 'inherit'}>
                    {fmt(t.amount)}
                  </Box>
                ),
              },
              { id: 'source', header: 'Source', cell: (t) => t.import_source || '—' },
              { id: 'status', header: 'Status', cell: (t) => txnStatusBadge(t.status) },
              {
                id: 'actions',
                header: '',
                cell: (t) =>
                  t.status === 'cleared' ? null : (
                    <Button variant="inline-link" onClick={() => deleteTransaction(t)}>
                      Delete
                    </Button>
                  ),
              },
            ]}
          />
        )}

        {selectedAccount && (
          <Table<BankReconciliation>
            header={
              <Header
                variant="h2"
                counter={`(${reconciliations.length})`}
                actions={
                  <Button variant="primary" onClick={() => setReconModalOpen(true)}>
                    New reconciliation
                  </Button>
                }
              >
                Reconciliations
              </Header>
            }
            items={reconciliations}
            variant="container"
            empty={<Box textAlign="center" color="inherit">No reconciliations yet.</Box>}
            columnDefinitions={[
              { id: 'stmt', header: 'Statement date', cell: (r) => r.statement_date },
              { id: 'beginning', header: 'Beginning', cell: (r) => <Box textAlign="right">{fmt(r.beginning_balance)}</Box> },
              { id: 'ending', header: 'Ending', cell: (r) => <Box textAlign="right">{fmt(r.ending_balance)}</Box> },
              { id: 'difference', header: 'Difference', cell: (r) => <Box textAlign="right">{fmt(r.summary.difference)}</Box> },
              { id: 'status', header: 'Status', cell: (r) => statusBadge(r.status) },
              {
                id: 'actions',
                header: '',
                cell: (r) => (
                  <Button variant="inline-link" onClick={() => openReport(r.id)}>
                    Open
                  </Button>
                ),
              },
            ]}
          />
        )}

        {report && summary && (
          <Container
            header={
              <Header
                variant="h2"
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    {isInProgress ? (
                      <Button
                        variant="primary"
                        disabled={!summary.is_balanced}
                        onClick={completeReconciliation}
                      >
                        Complete
                      </Button>
                    ) : (
                      <Button onClick={reopenReconciliation}>Reopen</Button>
                    )}
                  </SpaceBetween>
                }
              >
                Reconciliation — {report.reconciliation.statement_date} {statusBadge(report.reconciliation.status)}
              </Header>
            }
          >
            <SpaceBetween size="l">
              <ColumnLayout columns={4} variant="text-grid">
                <div>
                  <Box variant="awsui-key-label">Beginning balance</Box>
                  <div>{fmt(summary.beginning_balance)}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Cleared deposits</Box>
                  <div>{fmt(summary.cleared_deposits)}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Cleared withdrawals</Box>
                  <div>{fmt(summary.cleared_withdrawals)}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Cleared balance</Box>
                  <div>{fmt(summary.cleared_balance)}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Statement ending balance</Box>
                  <div>{fmt(summary.ending_balance)}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Difference</Box>
                  <div>
                    <Badge color={summary.is_balanced ? 'green' : 'red'}>{fmt(summary.difference)}</Badge>
                  </div>
                </div>
                <div>
                  <Box variant="awsui-key-label">GL book balance</Box>
                  <div>{fmt(report.gl_book_balance)}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Cleared items</Box>
                  <div>{summary.cleared_count}</div>
                </div>
              </ColumnLayout>

              <Table<BankTransaction>
                header={<Header variant="h3">Cleared transactions</Header>}
                items={report.cleared_transactions}
                variant="embedded"
                empty={<Box textAlign="center" color="inherit">Nothing cleared yet.</Box>}
                columnDefinitions={[
                  {
                    id: 'cleared',
                    header: 'Cleared',
                    cell: (t) => (
                      <Checkbox
                        checked
                        disabled={!isInProgress}
                        onChange={() => toggleCleared(t, false)}
                      />
                    ),
                  },
                  { id: 'date', header: 'Date', cell: (t) => t.txn_date },
                  { id: 'description', header: 'Description', cell: (t) => t.description || '—' },
                  { id: 'amount', header: 'Amount', cell: (t) => <Box textAlign="right">{fmt(t.amount)}</Box> },
                ]}
              />

              <Table<BankTransaction>
                header={<Header variant="h3">Outstanding transactions</Header>}
                items={report.outstanding_transactions}
                variant="embedded"
                empty={<Box textAlign="center" color="inherit">No outstanding transactions.</Box>}
                columnDefinitions={[
                  {
                    id: 'cleared',
                    header: 'Cleared',
                    cell: (t) => (
                      <Checkbox
                        checked={false}
                        disabled={!isInProgress}
                        onChange={() => toggleCleared(t, true)}
                      />
                    ),
                  },
                  { id: 'date', header: 'Date', cell: (t) => t.txn_date },
                  { id: 'description', header: 'Description', cell: (t) => t.description || '—' },
                  { id: 'amount', header: 'Amount', cell: (t) => <Box textAlign="right">{fmt(t.amount)}</Box> },
                ]}
              />
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>

      {/* New bank account modal */}
      <Modal
        visible={acctModalOpen}
        onDismiss={() => setAcctModalOpen(false)}
        header="New bank account"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setAcctModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingAcct} onClick={submitAccount}>Create</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Name">
            <Input value={acctName} onChange={({ detail }) => setAcctName(detail.value)} placeholder="Operating Checking" />
          </FormField>
          <FormField label="GL cash account" description="The asset account this bank account posts to.">
            <Select
              selectedOption={cashAccountOpts.find((o) => o.value === acctGlId) ?? null}
              onChange={({ detail }) => setAcctGlId(detail.selectedOption?.value ?? '')}
              options={cashAccountOpts}
              placeholder="Select a cash (asset) account"
              empty="No asset accounts available"
              filteringType="auto"
            />
          </FormField>
          <FormField label="Institution (optional)">
            <Input value={acctInstitution} onChange={({ detail }) => setAcctInstitution(detail.value)} />
          </FormField>
          <FormField label="Account number (last 4, optional)">
            <Input value={acctLast4} onChange={({ detail }) => setAcctLast4(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Manual transaction modal */}
      <Modal
        visible={txnModalOpen}
        onDismiss={() => setTxnModalOpen(false)}
        header="Add transaction"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setTxnModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingTxn} onClick={submitTransaction}>Add</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Date">
            <Input type="date" value={txnDate} onChange={({ detail }) => setTxnDate(detail.value)} />
          </FormField>
          <FormField label="Amount" description="Positive for deposits, negative for withdrawals.">
            <Input type="number" value={txnAmount} onChange={({ detail }) => setTxnAmount(detail.value)} placeholder="0.00" />
          </FormField>
          <FormField label="Description (optional)">
            <Input value={txnDescription} onChange={({ detail }) => setTxnDescription(detail.value)} />
          </FormField>
          <FormField label="Reference (optional)">
            <Input value={txnReference} onChange={({ detail }) => setTxnReference(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* New reconciliation modal */}
      <Modal
        visible={reconModalOpen}
        onDismiss={() => setReconModalOpen(false)}
        header="New reconciliation"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setReconModalOpen(false)}>Cancel</Button>
              <Button variant="primary" loading={savingRecon} onClick={submitReconciliation}>Start</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Statement date">
            <Input type="date" value={stmtDate} onChange={({ detail }) => setStmtDate(detail.value)} />
          </FormField>
          <FormField
            label="Beginning balance (optional)"
            description="Defaults to the prior reconciliation's ending balance."
          >
            <Input type="number" value={beginningBalance} onChange={({ detail }) => setBeginningBalance(detail.value)} placeholder="0.00" />
          </FormField>
          <FormField label="Statement ending balance">
            <Input type="number" value={endingBalance} onChange={({ detail }) => setEndingBalance(detail.value)} placeholder="0.00" />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default BankReconciliationPage;
