import React, { useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import BarChart from '@cloudscape-design/components/bar-chart';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Table from '@cloudscape-design/components/table';
import Badge from '@cloudscape-design/components/badge';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import { dashboard as dashboardApi, reports as reportsApi } from '@/api';
import type {
  TicketVolumeMonth,
  TopOfficeByTickets,
  LeaseRiskBucket,
  PortfolioHealthScore,
  CostPerSqftRow,
  MaintenanceSpendMonth,
  SpaceUtilizationRow,
} from '@/types';

interface HvacRow { year: number; total_cost: number; issue_count: number; }
interface ResolutionRow { label: string; avg_days: number; count: number; }

const BUCKET_COLORS: Record<string, string> = {
  expired: '#d13212',
  critical: '#e07941',
  warning: '#f89256',
  healthy: '#1d8102',
};

const healthColor = (score: number) => {
  if (score >= 80) return '#1d8102';
  if (score >= 60) return '#e07941';
  return '#d13212';
};

const fmtCurrency = (n: number | null) =>
  n == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

const fmtSqft = (n: number | null) =>
  n == null ? '—' : `${n.toLocaleString(undefined, { maximumFractionDigits: 0 })} sqft`;

const ScoreGauge: React.FC<{ label: string; score: number; description?: string }> = ({
  label, score, description,
}) => (
  <Box>
    <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">{label}</Box>
    <Box fontSize="display-l" fontWeight="bold" color="inherit" padding={{ bottom: 'xxs' }}
      style={{ color: healthColor(score) } as React.CSSProperties}>
      {score}
    </Box>
    <ProgressBar value={score} additionalInfo={description} />
  </Box>
);

const AnalyticsPage: React.FC = () => {
  const [health, setHealth] = useState<PortfolioHealthScore | null>(null);
  const [volumeTrend, setVolumeTrend] = useState<TicketVolumeMonth[]>([]);
  const [topOffices, setTopOffices] = useState<TopOfficeByTickets[]>([]);
  const [leaseRisk, setLeaseRisk] = useState<LeaseRiskBucket[]>([]);
  const [hvacData, setHvacData] = useState<HvacRow[]>([]);
  const [resByPriority, setResByPriority] = useState<ResolutionRow[]>([]);
  const [resByCategory, setResByCategory] = useState<ResolutionRow[]>([]);
  const [costPerSqft, setCostPerSqft] = useState<CostPerSqftRow[]>([]);
  const [maintenanceSpend, setMaintenanceSpend] = useState<MaintenanceSpendMonth[]>([]);
  const [spaceUtil, setSpaceUtil] = useState<SpaceUtilizationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [
          healthRes, trendRes, topRes, riskRes, hvacRes, resRes,
          cpsRes, spendRes, utilRes,
        ] = await Promise.all([
          dashboardApi.getPortfolioHealth(),
          dashboardApi.getTicketVolumeTrend(12),
          dashboardApi.getTopOfficesByTickets(8),
          dashboardApi.getLeaseRisk(),
          reportsApi.hvacCostAnalytics(),
          reportsApi.ticketResolutionAnalytics(),
          dashboardApi.getCostPerSqft(),
          dashboardApi.getMaintenanceSpend(12),
          dashboardApi.getSpaceUtilization(),
        ]);
        setHealth(healthRes.data);
        setVolumeTrend(trendRes.data);
        setTopOffices(topRes.data);
        setLeaseRisk(riskRes.data);
        setHvacData(hvacRes.data);
        setResByPriority(resRes.data.by_priority);
        setResByCategory(resRes.data.by_category);
        setCostPerSqft(cpsRes.data);
        setMaintenanceSpend(spendRes.data);
        setSpaceUtil(utilRes.data);
      } catch {
        setError('Failed to load analytics data.');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <ContentLayout header={<Header variant="h1">Analytics &amp; Executive Dashboard</Header>}>
      <SpaceBetween size="l">
        {error && <Alert type="error">{error}</Alert>}

        {/* ── Portfolio Health Score ── */}
        {health && (
          <Container header={<Header variant="h2">Portfolio Health Score</Header>}>
            <SpaceBetween size="l">
              <Box textAlign="center">
                <Box fontSize="body-s" fontWeight="bold" color="text-body-secondary">OVERALL HEALTH</Box>
                <div style={{ fontSize: 72, fontWeight: 700, color: healthColor(health.overall), lineHeight: 1 }}>
                  {health.overall}
                </div>
                <Box color="text-body-secondary" fontSize="body-s">out of 100</Box>
              </Box>
              <ColumnLayout columns={3} borders="vertical">
                <ScoreGauge
                  label="Lease Health"
                  score={health.lease_health}
                  description={`${health.lease_expiry_risk_pct}% expiring ≤90d`}
                />
                <ScoreGauge
                  label="Ticket Health"
                  score={health.ticket_health}
                  description={`${health.open_high_pct}% of open tickets high priority`}
                />
                <ScoreGauge
                  label="HVAC Compliance"
                  score={health.hvac_health}
                  description={`${health.hvac_overdue_pct}% overdue`}
                />
              </ColumnLayout>
              <ColumnLayout columns={2} borders="vertical">
                <Box>
                  <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">SLA COMPLIANCE</Box>
                  <Box fontSize="heading-xl" fontWeight="bold">{health.sla_compliance_pct}%</Box>
                  <Box color="text-body-secondary" fontSize="body-s">of closed tickets resolved within SLA</Box>
                </Box>
                <Box>
                  <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">HIGH-PRIORITY OPEN</Box>
                  <Box fontSize="heading-xl" fontWeight="bold">{health.open_high_pct}%</Box>
                  <Box color="text-body-secondary" fontSize="body-s">of open tickets are high priority</Box>
                </Box>
              </ColumnLayout>
            </SpaceBetween>
          </Container>
        )}

        {/* ── Space Utilization ── */}
        <Container header={<Header variant="h2">Space Utilization by Office</Header>}>
          {spaceUtil.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">
              No space data. Add sqft and headcount to your office records to see utilization.
            </Box>
          ) : (
            <SpaceBetween size="m">
              <ColumnLayout columns={4}>
                {[
                  {
                    label: 'Offices Tracked',
                    value: spaceUtil.filter(r => r.total_sqft).length,
                    suffix: '',
                  },
                  {
                    label: 'Total Portfolio Sqft',
                    value: spaceUtil.reduce((s, r) => s + (r.total_sqft ?? 0), 0).toLocaleString(undefined, { maximumFractionDigits: 0 }),
                    suffix: ' sqft',
                  },
                  {
                    label: 'Avg Occupancy',
                    value: (() => {
                      const tracked = spaceUtil.filter(r => r.occupancy_pct != null);
                      if (!tracked.length) return '—';
                      return (tracked.reduce((s, r) => s + (r.occupancy_pct ?? 0), 0) / tracked.length).toFixed(1);
                    })(),
                    suffix: (v: string) => v === '—' ? '' : '%',
                  },
                  {
                    label: 'Total Headcount',
                    value: spaceUtil.reduce((s, r) => s + (r.current_headcount ?? 0), 0),
                    suffix: ' people',
                  },
                ].map(({ label, value, suffix }) => (
                  <Box key={label} textAlign="center" padding="s">
                    <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">{label}</Box>
                    <Box fontSize="heading-xl" fontWeight="bold">
                      {value}{typeof suffix === 'function' ? suffix(String(value)) : suffix}
                    </Box>
                  </Box>
                ))}
              </ColumnLayout>
              <Table
                columnDefinitions={[
                  {
                    id: 'office',
                    header: 'Office',
                    cell: (r: SpaceUtilizationRow) =>
                      r.office_number ? `#${r.office_number} — ${r.office_name}` : r.office_name,
                  },
                  {
                    id: 'sqft',
                    header: 'Total Sqft',
                    cell: (r: SpaceUtilizationRow) => fmtSqft(r.total_sqft),
                  },
                  {
                    id: 'usable',
                    header: 'Usable Sqft',
                    cell: (r: SpaceUtilizationRow) => fmtSqft(r.usable_sqft),
                  },
                  {
                    id: 'headcount',
                    header: 'Headcount',
                    cell: (r: SpaceUtilizationRow) =>
                      r.current_headcount != null
                        ? `${r.current_headcount} / ${r.headcount_capacity ?? '?'}`
                        : '—',
                  },
                  {
                    id: 'occupancy',
                    header: 'Occupancy',
                    cell: (r: SpaceUtilizationRow) =>
                      r.occupancy_pct != null ? (
                        <ProgressBar
                          value={r.occupancy_pct}
                          additionalInfo={`${r.occupancy_pct}%`}
                          status={r.occupancy_pct > 90 ? 'error' : r.occupancy_pct > 75 ? 'in-progress' : 'success'}
                        />
                      ) : '—',
                  },
                  {
                    id: 'spp',
                    header: 'Sqft / Person',
                    cell: (r: SpaceUtilizationRow) =>
                      r.sqft_per_person != null ? `${r.sqft_per_person}` : '—',
                  },
                ]}
                items={spaceUtil}
                empty={<Box textAlign="center" color="inherit" padding="l">No data.</Box>}
              />
            </SpaceBetween>
          )}
        </Container>

        {/* ── Cost per Sqft ── */}
        <Container header={<Header variant="h2">Annual Cost per Square Foot</Header>}>
          {costPerSqft.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">
              No cost data. Ensure leases have payment amounts and offices have sqft.
            </Box>
          ) : (
            <SpaceBetween size="m">
              {(() => {
                const withData = costPerSqft.filter(r => r.cost_per_sqft != null);
                const avg = withData.length
                  ? withData.reduce((s, r) => s + (r.cost_per_sqft ?? 0), 0) / withData.length
                  : null;
                return avg != null ? (
                  <Box>
                    <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">PORTFOLIO AVERAGE</Box>
                    <Box fontSize="heading-xl" fontWeight="bold">{fmtCurrency(avg)}/sqft/yr</Box>
                  </Box>
                ) : null;
              })()}
              <Table
                columnDefinitions={[
                  {
                    id: 'office',
                    header: 'Office',
                    cell: (r: CostPerSqftRow) =>
                      r.office_number ? `#${r.office_number} — ${r.office_name}` : r.office_name,
                  },
                  {
                    id: 'sqft',
                    header: 'Total Sqft',
                    cell: (r: CostPerSqftRow) => fmtSqft(r.total_sqft),
                  },
                  {
                    id: 'rent',
                    header: 'Annual Rent',
                    cell: (r: CostPerSqftRow) => fmtCurrency(r.annual_rent),
                  },
                  {
                    id: 'opex',
                    header: 'OpEx (YTD)',
                    cell: (r: CostPerSqftRow) => fmtCurrency(r.opex_actual),
                  },
                  {
                    id: 'total',
                    header: 'Total Annual Cost',
                    cell: (r: CostPerSqftRow) => fmtCurrency(r.total_annual_cost),
                  },
                  {
                    id: 'cpp',
                    header: 'Cost/Sqft/Yr',
                    cell: (r: CostPerSqftRow) =>
                      r.cost_per_sqft != null ? (
                        <Box fontWeight="bold">{fmtCurrency(r.cost_per_sqft)}</Box>
                      ) : '—',
                  },
                ]}
                items={costPerSqft}
                empty={<Box textAlign="center" color="inherit" padding="l">No data.</Box>}
              />
              {/* ── OpEx breakdown by category ── */}
              {costPerSqft.some(r => Object.keys(r.opex_by_category ?? {}).length > 0) && (() => {
                const CATS: { key: string; label: string }[] = [
                  { key: 'cam', label: 'CAM' },
                  { key: 'insurance', label: 'Insurance' },
                  { key: 'taxes', label: 'Taxes' },
                  { key: 'utilities', label: 'Utilities' },
                  { key: 'other', label: 'Other' },
                ];
                const officesWithSqft = costPerSqft.filter(r => r.total_sqft);
                const xLabels = officesWithSqft.map(r =>
                  r.office_number ? `#${r.office_number}` : r.office_name.slice(0, 14)
                );
                return (
                  <SpaceBetween size="m">
                    <Header variant="h3">OpEx Cost per Sqft — by Category</Header>
                    <BarChart
                      series={CATS.map(({ key, label }) => ({
                        title: label,
                        type: 'bar' as const,
                        data: officesWithSqft.map(r => ({
                          x: r.office_number ? `#${r.office_number}` : r.office_name.slice(0, 14),
                          y: r.total_sqft
                            ? Math.round(((r.opex_by_category?.[key] ?? 0) / r.total_sqft) * 100) / 100
                            : 0,
                        })),
                        valueFormatter: (v: number) => `$${v}/sqft`,
                      }))}
                      xDomain={xLabels}
                      yTitle="$/sqft/yr"
                      xTitle="Office"
                      height={260}
                      stackedBars
                      empty={<Box textAlign="center">No data</Box>}
                    />
                    <Table
                      columnDefinitions={[
                        { id: 'cat', header: 'Category', cell: (r: { key: string; label: string; total: number; cpp: number | null }) => r.label },
                        {
                          id: 'total',
                          header: 'Portfolio Total (YTD)',
                          cell: (r) => fmtCurrency(r.total),
                        },
                        {
                          id: 'cpp',
                          header: 'Avg $/Sqft/Yr',
                          cell: (r) => r.cpp != null ? (
                            <Box fontWeight="bold">{fmtCurrency(r.cpp)}</Box>
                          ) : '—',
                        },
                      ]}
                      items={CATS.map(({ key, label }) => {
                        const total = costPerSqft.reduce((s, r) => s + (r.opex_by_category?.[key] ?? 0), 0);
                        const totalSqft = costPerSqft.reduce((s, r) => s + (r.total_sqft ?? 0), 0);
                        return {
                          key,
                          label,
                          total,
                          cpp: (total > 0 && totalSqft > 0) ? Math.round((total / totalSqft) * 100) / 100 : null,
                        };
                      }).filter(r => r.total > 0)}
                      empty={<Box textAlign="center" color="inherit">No OpEx category data.</Box>}
                      variant="embedded"
                    />
                  </SpaceBetween>
                );
              })()}
            </SpaceBetween>
          )}
        </Container>

        {/* ── Maintenance Spend Trend ── */}
        <Container header={<Header variant="h2">Maintenance Spend — Last 12 Months</Header>}>
          {maintenanceSpend.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">
              No maintenance cost data. Add cost lines to work orders to track spend.
            </Box>
          ) : (
            <SpaceBetween size="m">
              <BarChart
                series={[
                  {
                    title: 'Labor',
                    type: 'bar',
                    data: maintenanceSpend.map(r => ({ x: r.label, y: r.labor_total })),
                    valueFormatter: v => fmtCurrency(v),
                  },
                  {
                    title: 'Materials',
                    type: 'bar',
                    data: maintenanceSpend.map(r => ({ x: r.label, y: r.materials_total })),
                    valueFormatter: v => fmtCurrency(v),
                  },
                ]}
                xDomain={maintenanceSpend.map(r => r.label)}
                yTitle="Cost (USD)"
                xTitle="Month"
                height={280}
                stackedBars
                empty={<Box textAlign="center">No data</Box>}
              />
              <Box>
                <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">12-MONTH TOTAL</Box>
                <Box fontSize="heading-xl" fontWeight="bold">
                  {fmtCurrency(maintenanceSpend.reduce((s, r) => s + r.grand_total, 0))}
                </Box>
              </Box>
            </SpaceBetween>
          )}
        </Container>

        {/* ── Lease Risk Heatmap ── */}
        <Container header={<Header variant="h2">Lease Expiration Risk</Header>}>
          {leaseRisk.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">No lease data.</Box>
          ) : (
            <SpaceBetween size="m">
              <ColumnLayout columns={4}>
                {(['expired', 'critical', 'warning', 'healthy'] as const).map((bucket) => {
                  const item = leaseRisk.find((r) => r.bucket === bucket);
                  const labels: Record<string, string> = {
                    expired: 'Expired',
                    critical: 'Critical (≤30d)',
                    warning: 'Warning (≤90d)',
                    healthy: 'Healthy',
                  };
                  return (
                    <Box key={bucket} padding="s" textAlign="center">
                      <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">
                        {labels[bucket]}
                      </Box>
                      <div style={{ fontSize: 48, fontWeight: 700, color: BUCKET_COLORS[bucket] }}>
                        {item?.count ?? 0}
                      </div>
                      <Badge color={bucket === 'healthy' ? 'green' : bucket === 'warning' ? 'blue' : 'red'}>
                        {labels[bucket]}
                      </Badge>
                    </Box>
                  );
                })}
              </ColumnLayout>
              <BarChart
                series={[{
                  title: 'Leases',
                  type: 'bar',
                  data: (['expired', 'critical', 'warning', 'healthy'] as const).map((b) => ({
                    x: b,
                    y: leaseRisk.find((r) => r.bucket === b)?.count ?? 0,
                  })),
                }]}
                xDomain={['expired', 'critical', 'warning', 'healthy']}
                yTitle="Lease count"
                xTitle="Risk bucket"
                height={220}
                empty={<Box textAlign="center">No data</Box>}
              />
            </SpaceBetween>
          )}
        </Container>

        {/* ── Ticket Volume Trend ── */}
        <Container header={<Header variant="h2">Ticket Volume — Last 12 Months</Header>}>
          {volumeTrend.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">No ticket data available.</Box>
          ) : (
            <BarChart
              series={[
                {
                  title: 'Opened',
                  type: 'bar',
                  data: volumeTrend.map((r) => ({ x: r.label, y: r.open })),
                },
                {
                  title: 'Closed',
                  type: 'bar',
                  data: volumeTrend.map((r) => ({ x: r.label, y: r.closed })),
                },
              ]}
              xDomain={volumeTrend.map((r) => r.label)}
              yTitle="Tickets"
              xTitle="Month"
              height={280}
              empty={<Box textAlign="center">No data</Box>}
            />
          )}
        </Container>

        {/* ── Top Offices by Ticket Count ── */}
        <Container header={<Header variant="h2">Most Active Offices (by Ticket Count)</Header>}>
          <Table
            items={topOffices}
            columnDefinitions={[
              {
                id: 'rank',
                header: '#',
                cell: (_: TopOfficeByTickets, idx: number) => idx + 1,
                width: 50,
              },
              {
                id: 'name',
                header: 'Office',
                cell: (r: TopOfficeByTickets) =>
                  r.office_number ? `#${r.office_number} — ${r.office_name}` : r.office_name,
              },
              {
                id: 'count',
                header: 'Ticket Count',
                cell: (r: TopOfficeByTickets) => (
                  <Box>
                    <ProgressBar value={(r.ticket_count / (topOffices[0]?.ticket_count || 1)) * 100}
                      additionalInfo={String(r.ticket_count)} />
                  </Box>
                ),
              },
            ]}
            empty={<Box textAlign="center" color="inherit" padding="l">No ticket data.</Box>}
          />
        </Container>

        {/* ── HVAC Cost by Year ── */}
        <Container header={<Header variant="h2">HQ HVAC Issue Costs by Year</Header>}>
          {hvacData.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">No HVAC cost data available.</Box>
          ) : (
            <BarChart
              series={[{
                title: 'Total Cost ($)',
                type: 'bar',
                data: hvacData.map((r) => ({ x: String(r.year), y: r.total_cost })),
                valueFormatter: (v) => `$${v.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
              }]}
              xDomain={hvacData.map((r) => String(r.year))}
              yTitle="Cost (USD)"
              xTitle="Year"
              height={280}
              empty={<Box textAlign="center">No data</Box>}
            />
          )}
        </Container>

        {/* ── SLA: Resolution Time ── */}
        <Container header={<Header variant="h2">Avg. Days to Close — By Priority &amp; Category</Header>}>
          <SpaceBetween size="l">
            {resByPriority.length > 0 && (
              <SpaceBetween size="s">
                <Header variant="h3">By Priority</Header>
                <BarChart
                  series={[{
                    title: 'Avg. Days to Close',
                    type: 'bar',
                    data: resByPriority.map((r) => ({ x: r.label, y: r.avg_days })),
                    valueFormatter: (v) => `${v}d`,
                  }]}
                  xDomain={resByPriority.map((r) => r.label)}
                  yTitle="Days"
                  xTitle="Priority"
                  height={220}
                  empty={<Box textAlign="center">No data</Box>}
                />
                <Table
                  columnDefinitions={[
                    { id: 'label', header: 'Priority', cell: (r: ResolutionRow) => r.label },
                    { id: 'avg', header: 'Avg Days', cell: (r: ResolutionRow) => r.avg_days },
                    { id: 'count', header: 'Tickets', cell: (r: ResolutionRow) => r.count },
                  ]}
                  items={resByPriority}
                />
              </SpaceBetween>
            )}
            {resByCategory.length > 0 && (
              <SpaceBetween size="s">
                <Header variant="h3">By Category</Header>
                <BarChart
                  series={[{
                    title: 'Avg. Days to Close',
                    type: 'bar',
                    data: resByCategory.map((r) => ({ x: r.label, y: r.avg_days })),
                    valueFormatter: (v) => `${v}d`,
                  }]}
                  xDomain={resByCategory.map((r) => r.label)}
                  yTitle="Days"
                  xTitle="Category"
                  height={280}
                  empty={<Box textAlign="center">No data</Box>}
                />
                <Table
                  columnDefinitions={[
                    { id: 'label', header: 'Category', cell: (r: ResolutionRow) => r.label },
                    { id: 'avg', header: 'Avg Days', cell: (r: ResolutionRow) => r.avg_days },
                    { id: 'count', header: 'Tickets', cell: (r: ResolutionRow) => r.count },
                  ]}
                  items={resByCategory}
                />
              </SpaceBetween>
            )}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default AnalyticsPage;
