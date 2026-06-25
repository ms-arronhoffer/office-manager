import React, { useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import BarChart from '@cloudscape-design/components/bar-chart';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Table from '@cloudscape-design/components/table';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { reports as reportsApi } from '@/api';
import type { SlaAnalyticsResponse, SlaOfficeRow, SlaResolutionRow } from '@/types';

function breachColor(rate: number): 'error' | 'warning' | 'success' {
  if (rate > 0.5) return 'error';
  if (rate > 0.25) return 'warning';
  return 'success';
}

const SlaDashboardPage: React.FC = () => {
  const [data, setData] = useState<SlaAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await reportsApi.slaAnalytics();
        setData(res.data);
      } catch {
        setError('Failed to load SLA data.');
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

  const totalOpen = data?.open_summary.reduce((s, r) => s + r.total, 0) ?? 0;
  const totalBreached = data?.open_summary.reduce((s, r) => s + r.breached, 0) ?? 0;
  const overallRate = totalOpen > 0 ? totalBreached / totalOpen : 0;

  return (
    <ContentLayout header={<Header variant="h1">SLA Dashboard</Header>}>
      <SpaceBetween size="l">
        {error && <Alert type="error">{error}</Alert>}

        {/* Summary stats */}
        <Container header={<Header variant="h2">Overview</Header>}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '24px' }}>
            <div>
              <Box variant="awsui-key-label">Open Tickets</Box>
              <Box variant="h2">{totalOpen}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">SLA Breached</Box>
              <Box variant="h2">{totalBreached}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Overall Breach Rate</Box>
              <Box variant="h2">
                <StatusIndicator type={breachColor(overallRate)}>
                  {(overallRate * 100).toFixed(1)}%
                </StatusIndicator>
              </Box>
            </div>
          </div>
          {data && (
            <Box padding={{ top: 's' }} fontSize="body-s" color="text-body-secondary">
              SLA thresholds — High: {data.sla_thresholds.high}d, Medium: {data.sla_thresholds.medium}d, Low: {data.sla_thresholds.low}d
            </Box>
          )}
        </Container>

        {/* Breach rate by priority */}
        <Container header={<Header variant="h2">Breach Rate by Priority</Header>}>
          {!data || data.open_summary.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">No open ticket data available.</Box>
          ) : (
            <BarChart
              series={[
                {
                  title: 'Breach Rate (%)',
                  type: 'bar',
                  data: data.open_summary.map((r) => ({ x: r.priority.charAt(0).toUpperCase() + r.priority.slice(1), y: parseFloat((r.breach_rate * 100).toFixed(1)) })),
                  valueFormatter: (v) => `${v}%`,
                },
              ]}
              xDomain={data.open_summary.map((r) => r.priority.charAt(0).toUpperCase() + r.priority.slice(1))}
              yTitle="Breach Rate (%)"
              xTitle="Priority"
              height={250}
              empty={<Box textAlign="center">No data</Box>}
            />
          )}
        </Container>

        {/* Breach by office */}
        <Container header={<Header variant="h2">Breach by Office</Header>}>
          {!data || data.by_office.length === 0 ? (
            <Box textAlign="center" color="inherit" padding="l">No open ticket data available.</Box>
          ) : (
            <Table
              columnDefinitions={[
                { id: 'office', header: 'Office', cell: (r: SlaOfficeRow) => r.office },
                {
                  id: 'priority',
                  header: 'Priority',
                  cell: (r: SlaOfficeRow) => r.priority.charAt(0).toUpperCase() + r.priority.slice(1),
                },
                { id: 'total', header: 'Open', cell: (r: SlaOfficeRow) => r.total },
                { id: 'breached', header: 'Breached', cell: (r: SlaOfficeRow) => r.breached },
                {
                  id: 'breach_rate',
                  header: 'Breach Rate',
                  cell: (r: SlaOfficeRow) => (
                    <StatusIndicator type={breachColor(r.breach_rate)}>
                      {(r.breach_rate * 100).toFixed(1)}%
                    </StatusIndicator>
                  ),
                },
                { id: 'avg_days', header: 'Avg Days Open', cell: (r: SlaOfficeRow) => `${r.avg_days_open}d` },
              ]}
              items={data.by_office}
              empty={<Box textAlign="center" padding="m">No data</Box>}
            />
          )}
        </Container>

        {/* Resolution time */}
        {data?.resolution_summary && data.resolution_summary.length > 0 && (
          <Container header={<Header variant="h2">Avg Resolution Time (Closed Tickets)</Header>}>
            <Table
              columnDefinitions={[
                {
                  id: 'priority',
                  header: 'Priority',
                  cell: (r: SlaResolutionRow) => r.priority.charAt(0).toUpperCase() + r.priority.slice(1),
                },
                { id: 'resolved_count', header: 'Resolved', cell: (r: SlaResolutionRow) => r.resolved_count },
                {
                  id: 'avg_resolution_days',
                  header: 'Avg Resolution Time',
                  cell: (r: SlaResolutionRow) => `${r.avg_resolution_days}d`,
                },
              ]}
              items={data.resolution_summary}
              empty={<Box textAlign="center" padding="m">No resolved tickets with tracking data</Box>}
            />
          </Container>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default SlaDashboardPage;
