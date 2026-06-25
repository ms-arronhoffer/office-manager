import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Grid from '@cloudscape-design/components/grid';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import {
  dashboard,
  leases as leasesApi,
  reports as reportsApi,
  operatingExpenses as operatingExpensesApi,
} from '@/api';
import type {
  DashboardSummary,
  RentRollResponse,
  LeasePortfolioResponse,
  OperatingExpenseVariance,
  LeaseRiskBucket,
} from '@/types';

function formatCurrency(value: number | null | undefined, currency = 'USD'): string {
  if (value == null) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatPct(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${(value * 100).toFixed(2)}%`;
}

const KpiTile: React.FC<{
  label: string;
  value: string;
  description?: string;
  status?: 'success' | 'warning' | 'error' | 'info';
  onClick?: () => void;
}> = ({ label, value, description, status, onClick }) => (
  <Container>
    <div style={onClick ? { cursor: 'pointer' } : undefined} onClick={onClick}>
      <SpaceBetween size="xxs">
        <Box variant="awsui-key-label">{label}</Box>
        {status ? (
          <Box variant="h1" fontSize="display-l">
            <StatusIndicator type={status}>{value}</StatusIndicator>
          </Box>
        ) : (
          <Box variant="h1" fontSize="display-l" fontWeight="bold">{value}</Box>
        )}
        {description && (
          <Box variant="small" color="text-body-secondary">{description}</Box>
        )}
      </SpaceBetween>
    </div>
  </Container>
);

const RISK_LABELS: Record<LeaseRiskBucket['bucket'], { label: string; type: 'error' | 'warning' | 'info' | 'success' }> = {
  expired: { label: 'Expired', type: 'error' },
  critical: { label: 'Critical (< 90 days)', type: 'error' },
  warning: { label: 'Warning (< 180 days)', type: 'warning' },
  healthy: { label: 'Healthy', type: 'success' },
};

const FinancialDashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [rentRoll, setRentRoll] = useState<RentRollResponse | null>(null);
  const [portfolio, setPortfolio] = useState<LeasePortfolioResponse | null>(null);
  const [variance, setVariance] = useState<OperatingExpenseVariance[] | null>(null);
  const [risk, setRisk] = useState<LeaseRiskBucket[]>([]);
  const [partialError, setPartialError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true);
      const [summaryRes, rentRollRes, portfolioRes, varianceRes, riskRes] = await Promise.allSettled([
        dashboard.getSummary(),
        leasesApi.rentRoll(),
        reportsApi.leaseAccountingPortfolio(),
        operatingExpensesApi.variance(),
        dashboard.getLeaseRisk(),
      ]);
      if (!active) return;
      const failed: string[] = [];
      if (summaryRes.status === 'fulfilled') setSummary(summaryRes.value.data); else failed.push('summary');
      if (rentRollRes.status === 'fulfilled') setRentRoll(rentRollRes.value.data); else failed.push('rent roll');
      if (portfolioRes.status === 'fulfilled') setPortfolio(portfolioRes.value.data); else failed.push('lease accounting portfolio');
      if (varianceRes.status === 'fulfilled') setVariance(varianceRes.value.data); else failed.push('CAM variance');
      if (riskRes.status === 'fulfilled') setRisk(riskRes.value.data); else failed.push('expiration risk');
      setPartialError(failed.length > 0 ? `Some data could not be loaded: ${failed.join(', ')}.` : null);
      setLoading(false);
    };
    load();
    return () => { active = false; };
  }, []);

  const totalLiability = portfolio
    ? portfolio.total_current_liability + portfolio.total_noncurrent_liability
    : null;

  const camOverBudget = (variance ?? []).filter(
    (v) => v.budgeted != null && v.actual != null && v.actual > v.budgeted,
  );
  const camOverage = camOverBudget.reduce(
    (sum, v) => sum + ((v.actual ?? 0) - (v.budgeted ?? 0)),
    0,
  );

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Executive overview of lease portfolio financials, drawn from rent roll, ASC 842 / IFRS 16 accounting, and operating expenses."
          actions={
            <Button iconName="external" onClick={() => navigate('/reports')}>
              Reports &amp; exports
            </Button>
          }
        >
          Financial Dashboard
        </Header>
      }
    >
      <SpaceBetween size="l">
        {partialError && <Alert type="warning">{partialError}</Alert>}

        {/* Headline KPIs */}
        <Grid
          gridDefinition={[
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
          ]}
        >
          <KpiTile
            label="Total Annual Rent Obligation"
            value={formatCurrency(rentRoll?.total_annual)}
            description={rentRoll ? `${formatCurrency(rentRoll.total_monthly)} / month` : undefined}
            onClick={() => navigate('/rent-roll')}
          />
          <KpiTile
            label="Total ROU Asset"
            value={formatCurrency(portfolio?.total_rou)}
            description="Right-of-use assets"
            onClick={() => navigate('/reports')}
          />
          <KpiTile
            label="Total Lease Liability"
            value={formatCurrency(totalLiability)}
            description={
              portfolio
                ? `${formatCurrency(portfolio.total_current_liability)} current`
                : undefined
            }
            onClick={() => navigate('/reports')}
          />
          <KpiTile
            label="Leases Expiring < 90 Days"
            value={String(summary?.upcoming_expirations_90d ?? 0)}
            status={summary?.upcoming_expirations_90d ? 'warning' : 'success'}
            onClick={() => navigate('/leases?expiring_soon=90')}
          />
        </Grid>

        {/* Secondary KPIs */}
        <Grid
          gridDefinition={[
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
            { colspan: { default: 12, s: 6, m: 4, l: 3 } },
          ]}
        >
          <KpiTile
            label="Leases with Rent Data"
            value={String(rentRoll?.count ?? 0)}
            onClick={() => navigate('/rent-roll')}
          />
          <KpiTile
            label="Weighted Avg IBR"
            value={formatPct(portfolio?.weighted_avg_ibr)}
          />
          <KpiTile
            label="Weighted Avg Remaining Term"
            value={
              portfolio?.weighted_avg_remaining_months != null
                ? `${portfolio.weighted_avg_remaining_months.toFixed(1)} mo`
                : '—'
            }
          />
          <KpiTile
            label="CAM Categories Over Budget"
            value={String(camOverBudget.length)}
            description={camOverBudget.length > 0 ? `${formatCurrency(camOverage)} over` : 'Within budget'}
            status={camOverBudget.length > 0 ? 'warning' : 'success'}
            onClick={() => navigate('/operating-expenses')}
          />
        </Grid>

        {/* Lease accounting summary */}
        <Container
          header={
            <Header
              variant="h2"
              actions={<Link onFollow={() => navigate('/reports')}>View portfolio</Link>}
            >
              Lease Accounting (ASC 842 / IFRS 16)
            </Header>
          }
        >
          {portfolio ? (
            <ColumnLayout columns={4} variant="text-grid">
              <div>
                <Box variant="awsui-key-label">Right-of-Use Asset</Box>
                <Box>{formatCurrency(portfolio.total_rou)}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Current Liability</Box>
                <Box>{formatCurrency(portfolio.total_current_liability)}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Non-Current Liability</Box>
                <Box>{formatCurrency(portfolio.total_noncurrent_liability)}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Leases in Scope</Box>
                <Box>{portfolio.leases.length}</Box>
              </div>
            </ColumnLayout>
          ) : (
            <Box color="text-body-secondary">Lease accounting data is unavailable.</Box>
          )}
        </Container>

        {/* Lease expiration risk */}
        <Container
          header={
            <Header
              variant="h2"
              actions={<Link onFollow={() => navigate('/rent-roll')}>Open rent roll</Link>}
            >
              Lease Expiration Risk
            </Header>
          }
        >
          {risk.length > 0 ? (
            <ColumnLayout columns={4} variant="text-grid">
              {risk.map((b) => {
                const meta = RISK_LABELS[b.bucket];
                return (
                  <div key={b.bucket}>
                    <Box variant="awsui-key-label">{meta?.label ?? b.bucket}</Box>
                    <Box>
                      <StatusIndicator type={meta?.type ?? 'info'}>
                        {b.count} lease{b.count !== 1 ? 's' : ''}
                      </StatusIndicator>
                    </Box>
                  </div>
                );
              })}
            </ColumnLayout>
          ) : (
            <Box color="text-body-secondary">No lease expiration risk data available.</Box>
          )}
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default FinancialDashboardPage;
