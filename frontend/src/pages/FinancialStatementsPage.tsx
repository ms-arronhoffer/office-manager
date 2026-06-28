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
import { useFlashbar } from '@/context/FlashbarContext';
import { financials as finApi } from '@/api';
import type {
  IncomeStatementResponse,
  BalanceSheetResponse,
  CashFlowStatementResponse,
  StatementLine,
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

const FinancialStatementsPage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const now = new Date();
  const [year, setYear] = useState<Opt>({ label: String(now.getFullYear()), value: String(now.getFullYear()) });
  const [month, setMonth] = useState<Opt>(ALL_MONTHS);
  const [loading, setLoading] = useState(true);
  const [income, setIncome] = useState<IncomeStatementResponse | null>(null);
  const [balance, setBalance] = useState<BalanceSheetResponse | null>(null);
  const [cashFlow, setCashFlow] = useState<CashFlowStatementResponse | null>(null);

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
        ]}
      />
    </ContentLayout>
  );
};

export default FinancialStatementsPage;
