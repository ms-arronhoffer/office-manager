import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Tabs from '@cloudscape-design/components/tabs';
import Table from '@cloudscape-design/components/table';
import Box from '@cloudscape-design/components/box';
import Select from '@cloudscape-design/components/select';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Button from '@cloudscape-design/components/button';
import Spinner from '@cloudscape-design/components/spinner';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { financials as finApi } from '@/api';
import type {
  IncomeStatementResponse,
  BalanceSheetResponse,
  CashFlowStatementResponse,
  StatementLine,
  AuditReportResponse,
  AuditCheck,
  AuditControlAccount,
} from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

interface Opt { label: string; value: string; }

const ALL_YEARS: Opt = { label: 'All time', value: '' };
const ALL_MONTHS: Opt = { label: 'Full year', value: '' };

const lineColumns = [
  { id: 'code', header: 'Code', cell: (l: StatementLine) => l.code },
  { id: 'name', header: 'Account', cell: (l: StatementLine) => l.name },
  {
    id: 'amount',
    header: 'Amount',
    cell: (l: StatementLine) => <Box textAlign="right">{fmt(l.amount)}</Box>,
  },
];

const Section: React.FC<{
  title: string;
  lines: StatementLine[];
  total: number;
  totalLabel: string;
  loading?: boolean;
}> = ({ title, lines, total, totalLabel, loading }) => (
  <Container header={<Header variant="h3">{title}</Header>}>
    <Table
      variant="embedded"
      loading={loading}
      items={lines}
      columnDefinitions={lineColumns}
      empty={<Box textAlign="center" color="inherit">No activity.</Box>}
      footer={
        <Box textAlign="right" fontWeight="bold">
          {totalLabel}: {fmt(total)}
        </Box>
      }
    />
  </Container>
);

const checkColumns = [
  {
    id: 'status',
    header: 'Status',
    cell: (c: AuditCheck) => (
      <StatusIndicator type={c.status === 'pass' ? 'success' : 'error'}>
        {c.status === 'pass' ? 'Pass' : 'Fail'}
      </StatusIndicator>
    ),
  },
  { id: 'description', header: 'Check', cell: (c: AuditCheck) => c.description },
  { id: 'category', header: 'Category', cell: (c: AuditCheck) => c.category },
  {
    id: 'detail',
    header: 'Detail',
    cell: (c: AuditCheck) =>
      c.status === 'pass'
        ? c.detail
        : c.detail || `${c.finding_count} finding(s): ${c.findings.join('; ')}`,
  },
];

const controlColumns = [
  { id: 'code', header: 'Code', cell: (a: AuditControlAccount) => a.code },
  { id: 'name', header: 'Control account', cell: (a: AuditControlAccount) => a.name },
  {
    id: 'balance',
    header: 'Balance',
    cell: (a: AuditControlAccount) => (
      <Box textAlign="right">{fmt(a.balance)} ({a.balance_side})</Box>
    ),
  },
];

const AuditReportView: React.FC<{
  report: AuditReportResponse | null;
  loading: boolean;
  onRun: () => void;
}> = ({ report, loading, onRun }) => (
  <SpaceBetween size="l">
    <Container
      header={
        <Header
          variant="h3"
          description="Independently re-derives double-entry, line, scope, period, audit-trail, statement cross-tie and control-account invariants over the whole ledger."
          actions={
            <Button variant="primary" onClick={onRun} loading={loading} iconName="refresh">
              Run audit
            </Button>
          }
        >
          Attestation
        </Header>
      }
    >
      {loading && !report ? (
        <Box textAlign="center" padding="l"><Spinner /> Running audit…</Box>
      ) : !report ? (
        <Box textAlign="center" color="inherit" padding="l">
          Run the built-in auditor to attest the general ledger.
        </Box>
      ) : (
        <ColumnLayout columns={4} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Attested</Box>
            <StatusIndicator type={report.attested ? 'success' : 'error'}>
              {report.attested ? 'Attested' : 'Not attested'}
            </StatusIndicator>
          </div>
          <div>
            <Box variant="awsui-key-label">Checks passed</Box>
            {report.checks_passed} / {report.checks_total}
          </div>
          <div>
            <Box variant="awsui-key-label">Journal entries</Box>
            {report.entry_count}
          </div>
          <div>
            <Box variant="awsui-key-label">Σ debits = Σ credits</Box>
            {fmt(report.total_debits)}
          </div>
        </ColumnLayout>
      )}
    </Container>

    {report && (
      <Container header={<Header variant="h3">Audit checks</Header>}>
        <Table
          variant="embedded"
          items={report.checks}
          columnDefinitions={checkColumns}
          empty={<Box textAlign="center" color="inherit">No checks.</Box>}
        />
      </Container>
    )}

    {report && report.control_accounts.length > 0 && (
      <Container header={<Header variant="h3">Control accounts</Header>}>
        <Table
          variant="embedded"
          items={report.control_accounts}
          columnDefinitions={controlColumns}
          empty={<Box textAlign="center" color="inherit">No control accounts.</Box>}
        />
      </Container>
    )}
  </SpaceBetween>
);

const FinancialStatementsPage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const now = new Date();
  const [year, setYear] = useState<Opt>({ label: String(now.getFullYear()), value: String(now.getFullYear()) });
  const [month, setMonth] = useState<Opt>(ALL_MONTHS);
  const [loading, setLoading] = useState(true);
  const [income, setIncome] = useState<IncomeStatementResponse | null>(null);
  const [balance, setBalance] = useState<BalanceSheetResponse | null>(null);
  const [cashFlow, setCashFlow] = useState<CashFlowStatementResponse | null>(null);
  const [audit, setAudit] = useState<AuditReportResponse | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [pdfLoading, setPdfLoading] = useState<string | null>(null);

  const yearOptions = useMemo<Opt[]>(() => {
    const y = now.getFullYear();
    const opts: Opt[] = [ALL_YEARS];
    for (let i = 0; i < 8; i += 1) opts.push({ label: String(y - i), value: String(y - i) });
    return opts;
  }, [now]);

  const monthOptions = useMemo<Opt[]>(
    () => [ALL_MONTHS, ...MONTHS.map((m, i) => ({ label: m, value: String(i + 1) }))],
    [],
  );

  const load = useCallback(async () => {
    setLoading(true);
    const params: { year?: number; month?: number } = {};
    if (year.value) params.year = Number(year.value);
    if (month.value) params.month = Number(month.value);
    try {
      const [is, bs, cf] = await Promise.all([
        finApi.incomeStatement(params),
        finApi.balanceSheet(params),
        finApi.cashFlowStatement(params),
      ]);
      setIncome(is.data);
      setBalance(bs.data);
      setCashFlow(cf.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load financial statements.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash, year.value, month.value]);

  useEffect(() => { load(); }, [load]);

  const downloadPdf = useCallback(
    async (
      statement: 'income' | 'balance' | 'cash-flow',
      fetcher: () => Promise<{ data: Blob }>,
      filename: string,
    ) => {
      setPdfLoading(statement);
      try {
        const res = await fetcher();
        const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        window.URL.revokeObjectURL(url);
      } catch (err: unknown) {
        const responseStatus = (err as { response?: { status?: number } })?.response?.status;
        addFlash({
          type: 'error',
          content:
            responseStatus === 402
              ? 'PDF export is not included in your plan. Upgrade to enable it.'
              : 'Failed to generate PDF.',
        });
      } finally {
        setPdfLoading(null);
      }
    },
    [addFlash],
  );

  const pdfParams = useMemo(
    () => ({
      year: year.value ? Number(year.value) : undefined,
      month: month.value ? Number(month.value) : undefined,
    }),
    [year.value, month.value],
  );

  const runAudit = useCallback(async () => {
    setAuditLoading(true);
    try {
      const { data } = await finApi.auditReport();
      setAudit(data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to run accounting audit.' });
    } finally {
      setAuditLoading(false);
    }
  }, [addFlash]);

  const periodControls = (
    <SpaceBetween direction="horizontal" size="xs">
      <Select
        selectedOption={year}
        options={yearOptions}
        onChange={({ detail }) => setYear(detail.selectedOption as Opt)}
        ariaLabel="Year"
      />
      <Select
        selectedOption={month}
        options={monthOptions}
        onChange={({ detail }) => setMonth(detail.selectedOption as Opt)}
        ariaLabel="Month"
        disabled={!year.value}
      />
    </SpaceBetween>
  );

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="GAAP financial statements derived from the audit-grade general ledger."
          actions={periodControls}
        >
          Financial Statements
        </Header>
      }
    >
      <Tabs
        tabs={[
          {
            id: 'income',
            label: 'Income Statement',
            content: (
              <SpaceBetween size="l">
                <Box textAlign="right">
                  <Button
                    iconName="download"
                    loading={pdfLoading === 'income'}
                    disabled={loading}
                    onClick={() =>
                      downloadPdf('income', () => finApi.incomeStatementPdf(pdfParams), 'income_statement.pdf')
                    }
                  >
                    Download PDF
                  </Button>
                </Box>
                <Section
                  title="Revenue"
                  lines={income?.revenue ?? []}
                  total={income?.total_revenue ?? 0}
                  totalLabel="Total revenue"
                  loading={loading}
                />
                <Section
                  title="Expenses"
                  lines={income?.expenses ?? []}
                  total={income?.total_expenses ?? 0}
                  totalLabel="Total expenses"
                  loading={loading}
                />
                <Container header={<Header variant="h3">Net income</Header>}>
                  <Box variant="h1" textAlign="right">
                    <StatusIndicator type={(income?.net_income ?? 0) >= 0 ? 'success' : 'error'}>
                      {fmt(income?.net_income)}
                    </StatusIndicator>
                  </Box>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            id: 'balance',
            label: 'Balance Sheet',
            content: (
              <SpaceBetween size="l">
                <Box textAlign="right">
                  <Button
                    iconName="download"
                    loading={pdfLoading === 'balance'}
                    disabled={loading}
                    onClick={() =>
                      downloadPdf('balance', () => finApi.balanceSheetPdf(pdfParams), 'balance_sheet.pdf')
                    }
                  >
                    Download PDF
                  </Button>
                </Box>
                <Section
                  title="Assets"
                  lines={balance?.assets ?? []}
                  total={balance?.total_assets ?? 0}
                  totalLabel="Total assets"
                  loading={loading}
                />
                <Section
                  title="Liabilities"
                  lines={balance?.liabilities ?? []}
                  total={balance?.total_liabilities ?? 0}
                  totalLabel="Total liabilities"
                  loading={loading}
                />
                <Section
                  title="Equity"
                  lines={balance?.equity ?? []}
                  total={balance?.total_equity ?? 0}
                  totalLabel="Total equity"
                  loading={loading}
                />
                <Container header={<Header variant="h3">Balance check</Header>}>
                  <SpaceBetween size="xs">
                    <Box textAlign="right">
                      Liabilities &amp; equity: <strong>{fmt(balance?.liabilities_and_equity)}</strong>
                    </Box>
                    <Box textAlign="right">
                      <StatusIndicator type={balance?.balanced ? 'success' : 'warning'}>
                        {balance?.balanced ? 'Balanced' : 'Out of balance'}
                      </StatusIndicator>
                    </Box>
                  </SpaceBetween>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            id: 'cash-flow',
            label: 'Cash Flow',
            content: (
              <SpaceBetween size="l">
                <Box textAlign="right">
                  <Button
                    iconName="download"
                    loading={pdfLoading === 'cash-flow'}
                    disabled={loading}
                    onClick={() =>
                      downloadPdf(
                        'cash-flow',
                        () => finApi.cashFlowStatementPdf(pdfParams),
                        'cash_flow_statement.pdf',
                      )
                    }
                  >
                    Download PDF
                  </Button>
                </Box>
                <Section
                  title="Operating activities"
                  lines={cashFlow?.operating.lines ?? []}
                  total={cashFlow?.operating.total ?? 0}
                  totalLabel="Net cash from operating"
                  loading={loading}
                />
                <Section
                  title="Investing activities"
                  lines={cashFlow?.investing.lines ?? []}
                  total={cashFlow?.investing.total ?? 0}
                  totalLabel="Net cash from investing"
                  loading={loading}
                />
                <Section
                  title="Financing activities"
                  lines={cashFlow?.financing.lines ?? []}
                  total={cashFlow?.financing.total ?? 0}
                  totalLabel="Net cash from financing"
                  loading={loading}
                />
                <Container header={<Header variant="h3">Reconciliation</Header>}>
                  <SpaceBetween size="xs">
                    <Box textAlign="right">Beginning cash: <strong>{fmt(cashFlow?.beginning_cash)}</strong></Box>
                    <Box textAlign="right">Net change in cash: <strong>{fmt(cashFlow?.net_change_in_cash)}</strong></Box>
                    <Box textAlign="right">Ending cash: <strong>{fmt(cashFlow?.ending_cash)}</strong></Box>
                  </SpaceBetween>
                </Container>
              </SpaceBetween>
            ),
          },
          {
            id: 'attestation',
            label: 'Attestation',
            content: (
              <AuditReportView report={audit} loading={auditLoading} onRun={runAudit} />
            ),
          },
        ]}
      />
    </ContentLayout>
  );
};

export default FinancialStatementsPage;
