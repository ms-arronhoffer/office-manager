import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Grid from '@cloudscape-design/components/grid';
import Container from '@cloudscape-design/components/container';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import Alert from '@cloudscape-design/components/alert';
import BarChart from '@cloudscape-design/components/bar-chart';
import Badge from '@cloudscape-design/components/badge';
import Button from '@cloudscape-design/components/button';
import { dashboard, maintenanceTickets as ticketsApi, activityLog } from '@/api';
import type { DashboardSummary, LeaseExpirationByYear, Transition, MaintenanceTicket, ActivityLogEntry } from '@/types';
import { usePreferences } from '@/context/PreferencesContext';
import { useAuth } from '@/auth/AuthContext';
import DashboardSettingsModal from '@/components/dashboard/DashboardSettingsModal';

interface HvacDueItem {
  id: string;
  office_number?: number;
  office_name?: string;
  hvac_company?: string;
  next_service_date?: string;
  frequency?: string;
}

const DASHBOARD_WIDGETS = [
  { id: 'stat_cards', label: 'Summary Statistics' },
  { id: 'tickets_table', label: 'Open & In Progress Tickets' },
  { id: 'lease_chart', label: 'Lease Expirations Chart' },
  { id: 'hvac_table', label: 'Upcoming HVAC Services' },
  { id: 'transitions_table', label: 'Active Transitions' },
  { id: 'activity_feed', label: 'Recent Activity' },
];

function getDefaultWidgets(role: string): Record<string, boolean> {
  const defaults: Record<string, boolean> = {
    stat_cards: true,
    tickets_table: true,
    lease_chart: true,
    hvac_table: true,
    transitions_table: true,
    activity_feed: true,
  };
  if (role === 'ticketer') {
    defaults.lease_chart = false;
    defaults.hvac_table = false;
    defaults.transitions_table = false;
  }
  return defaults;
}

const StatBox: React.FC<{ label: string; value: number | string; status?: 'success' | 'warning' | 'error' | 'info'; onClick?: () => void }> = ({ label, value, status = 'info', onClick }) => (
  <Container>
    <div style={onClick ? { cursor: 'pointer' } : undefined} onClick={onClick}>
      <SpaceBetween size="xs">
        <Box variant="small" color="text-body-secondary">{label}</Box>
        <Box variant="h1" fontSize="display-l">
          <StatusIndicator type={status}>{value}</StatusIndicator>
        </Box>
      </SpaceBetween>
    </div>
  </Container>
);

const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { getDashboardWidgets } = usePreferences();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [expirations, setExpirations] = useState<LeaseExpirationByYear[]>([]);
  const [hvacDue, setHvacDue] = useState<HvacDueItem[]>([]);
  const [activeTransitions, setActiveTransitions] = useState<Transition[]>([]);
  const [openTickets, setOpenTickets] = useState<MaintenanceTicket[]>([]);
  const [recentActivity, setRecentActivity] = useState<ActivityLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Widget visibility: use user customization if any, otherwise role-based defaults
  const userWidgets = getDashboardWidgets();
  const hasCustomized = Object.keys(userWidgets).length > 0;
  const widgetConfig = hasCustomized ? userWidgets : getDefaultWidgets(user?.role ?? 'viewer');
  const isVisible = (id: string) => widgetConfig[id] !== false;

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [summaryRes, expRes, hvacRes, transRes, ticketsRes, activityRes] = await Promise.all([
          dashboard.getSummary(),
          dashboard.getLeaseExpirations(),
          dashboard.getHvacDue(),
          dashboard.getActiveTransitions(),
          ticketsApi.list({ status: 'open', page_size: 100 }),
          activityLog.recent(10),
        ]);
        setSummary(summaryRes.data);
        setExpirations(expRes.data);
        setHvacDue(hvacRes.data);
        setActiveTransitions(transRes.data);
        setRecentActivity(activityRes.data);
        // Combine open + in_progress tickets
        const openItems = ticketsRes.data.items || [];
        const inProgressRes = await ticketsApi.list({ status: 'in_progress', page_size: 100 });
        const inProgressItems = inProgressRes.data.items || [];
        setOpenTickets([...openItems, ...inProgressItems]);
      } catch (err) {
        console.error('Dashboard fetch error:', err);
        setError('Failed to load dashboard data. Please refresh the page.');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

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
          actions={
            <Button iconName="settings" variant="icon" onClick={() => setSettingsOpen(true)} ariaLabel="Dashboard settings" />
          }
        >
          Dashboard
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Summary Stats */}
        {isVisible('stat_cards') && (
          <Grid
            gridDefinition={[
              { colspan: { default: 12, s: 6, m: 4, l: 2 } },
              { colspan: { default: 12, s: 6, m: 4, l: 2 } },
              { colspan: { default: 12, s: 6, m: 4, l: 2 } },
              { colspan: { default: 12, s: 6, m: 4, l: 2 } },
              { colspan: { default: 12, s: 6, m: 4, l: 2 } },
              { colspan: { default: 12, s: 6, m: 4, l: 2 } },
              { colspan: { default: 12, s: 6, m: 4, l: 2 } },
            ]}
          >
            <StatBox
              label="Active Offices"
              value={summary?.active_offices ?? 0}
              status="success"
              onClick={() => navigate('/offices')}
            />
            <StatBox
              label="High Priority"
              value={summary?.high_priority_tickets ?? 0}
              status={summary?.high_priority_tickets ? 'error' : 'success'}
              onClick={() => navigate('/maintenance-tickets?priority=high')}
            />
            <StatBox
              label="Active Leases"
              value={summary?.active_leases ?? 0}
              status="success"
              onClick={() => navigate('/leases')}
            />
            <StatBox
              label="Expiring (90d)"
              value={summary?.upcoming_expirations_90d ?? 0}
              status={summary?.upcoming_expirations_90d ? 'warning' : 'success'}
              onClick={() => navigate('/leases?expiring_soon=90')}
            />
            <StatBox
              label="Overdue Notices"
              value={summary?.overdue_notices ?? 0}
              status={summary?.overdue_notices ? 'error' : 'success'}
              onClick={() => navigate('/leases?overdue_notices=true')}
            />
            <StatBox
              label="Overdue Tickets"
              value={summary?.overdue_tickets ?? 0}
              status={summary?.overdue_tickets ? 'error' : 'success'}
              onClick={() => navigate('/maintenance-tickets')}
            />
            <StatBox
              label="HVAC Due Soon"
              value={hvacDue.length}
              status={hvacDue.length > 0 ? 'warning' : 'success'}
              onClick={() => navigate('/hvac-contracts?due_soon=true')}
            />
          </Grid>
        )}

        {/* Open / In Progress Maintenance Tickets */}
        {isVisible('tickets_table') && (
          <Table
            header={
              <Header
                variant="h2"
                counter={`(${openTickets.length})`}
                actions={<Link onFollow={() => navigate('/maintenance-tickets')}>View all</Link>}
              >
                Open &amp; In Progress Tickets
              </Header>
            }
            columnDefinitions={[
              {
                id: 'subject',
                header: 'Subject',
                cell: (item) => (
                  <Link onFollow={() => navigate(`/maintenance-tickets/${item.id}`)}>
                    {item.subject}
                  </Link>
                ),
              },
              {
                id: 'priority',
                header: 'Priority',
                cell: (item) => {
                  const color = item.priority === 'high' ? 'red' : item.priority === 'medium' ? 'blue' : 'grey';
                  return <Badge color={color}>{item.priority.charAt(0).toUpperCase() + item.priority.slice(1)}</Badge>;
                },
              },
              {
                id: 'status',
                header: 'Status',
                cell: (item) => (
                  <StatusIndicator type={item.status === 'in_progress' ? 'in-progress' : 'pending'}>
                    {item.status === 'in_progress' ? 'In Progress' : 'Open'}
                  </StatusIndicator>
                ),
              },
              {
                id: 'category',
                header: 'Category',
                cell: (item) => item.category?.name || '—',
              },
              {
                id: 'office',
                header: 'Office',
                cell: (item) => item.office?.location_name || '—',
              },
              {
                id: 'created',
                header: 'Created',
                cell: (item) => item.created_at ? new Date(item.created_at).toLocaleDateString() : '—',
              },
            ]}
            items={openTickets}
            onRowClick={({ detail }) => navigate(`/maintenance-tickets/${detail.item.id}`)}
            empty={
              <Box textAlign="center" color="text-body-secondary" padding="l">
                No open or in-progress tickets
              </Box>
            }
            variant="embedded"
          />
        )}

        {/* Lease Expirations Chart */}
        {isVisible('lease_chart') && (
          <Container header={<Header variant="h2">Lease Expirations by Year</Header>}>
            {expirations.length > 0 ? (
              <BarChart
                series={[
                  {
                    title: 'Leases Expiring',
                    type: 'bar',
                    data: expirations.map((e) => ({ x: String(e.year), y: e.count })),
                    color: '#0972d3',
                  },
                ]}
                xDomain={expirations.map((e) => String(e.year))}
                yDomain={[0, Math.max(...expirations.map((e) => e.count)) + 1]}
                xTitle="Year"
                yTitle="Number of Leases"
                height={180}
                hideFilter
                hideLegend
                detailPopoverFooter={(xValue) => (
                  <Link onFollow={() => navigate(`/leases?expiration_year=${xValue}`)}>
                    View leases expiring in {xValue}
                  </Link>
                )}
                empty={
                  <Box textAlign="center" color="inherit">
                    <b>No data available</b>
                  </Box>
                }
              />
            ) : (
              <Box textAlign="center" color="text-body-secondary" padding="l">
                No lease expiration data available
              </Box>
            )}
          </Container>
        )}

        {/* HVAC Due Table */}
        {isVisible('hvac_table') && (
          <Table
            header={
              <Header
                variant="h2"
                counter={`(${hvacDue.length})`}
                actions={<Link onFollow={() => navigate('/hvac-contracts')}>View all</Link>}
              >
                Upcoming HVAC Services
              </Header>
            }
            columnDefinitions={[
              { id: 'company', header: 'HVAC Company', cell: (item) => (
                <Link onFollow={() => navigate(`/hvac-contracts/${item.id}`)}>{item.hvac_company || '—'}</Link>
              ) },
              { id: 'office', header: 'Office', cell: (item) => item.office_name || `#${item.office_number}` || '—' },
              { id: 'frequency', header: 'Frequency', cell: (item) => item.frequency || '—' },
              {
                id: 'next_service',
                header: 'Next Service',
                cell: (item) =>
                  item.next_service_date
                    ? new Date(item.next_service_date).toLocaleDateString()
                    : '—',
              },
            ]}
            items={hvacDue}
            onRowClick={({ detail }) => navigate(`/hvac-contracts/${detail.item.id}`)}
            empty={
              <Box textAlign="center" color="text-body-secondary" padding="l">
                No HVAC services due soon
              </Box>
            }
            variant="embedded"
          />
        )}

        {/* Active Transitions Table */}
        {isVisible('transitions_table') && (
          <Table
            header={
              <Header
                variant="h2"
                counter={`(${activeTransitions.length})`}
                actions={<Link onFollow={() => navigate('/transitions')}>View all</Link>}
              >
                Active Transitions
              </Header>
            }
            columnDefinitions={[
              {
                id: 'office',
                header: 'Office',
                cell: (item) => (
                  <Link onFollow={() => navigate(`/transitions/${item.id}`)}>
                    {item.address || `Office #${item.office_number}`}
                  </Link>
                ),
              },
              {
                id: 'type',
                header: 'Type',
                cell: (item) => <Box textTransform="capitalize">{item.transition_type.replace('_', ' ')}</Box>,
              },
              {
                id: 'status',
                header: 'Status',
                cell: (item) => {
                  const statusMap: Record<string, 'success' | 'in-progress' | 'pending' | 'error'> = {
                    completed: 'success',
                    in_progress: 'in-progress',
                    planned: 'pending',
                    cancelled: 'error',
                  };
                  return (
                    <StatusIndicator type={statusMap[item.status] || 'pending'}>
                      {item.status.replace('_', ' ')}
                    </StatusIndicator>
                  );
                },
              },
              {
                id: 'checklist',
                header: 'Checklist Progress',
                cell: (item) => {
                  const items = item.checklist_items || [];
                  const completed = items.filter((c) => c.is_complete).length;
                  return items.length > 0 ? `${completed}/${items.length}` : '—';
                },
              },
            ]}
            items={activeTransitions}
            empty={
              <Box textAlign="center" color="text-body-secondary" padding="l">
                No active transitions
              </Box>
            }
            variant="embedded"
          />
        )}

        {/* Recent Activity Feed */}
        {isVisible('activity_feed') && recentActivity.length > 0 && (
          <Table
            header={<Header variant="h2">Recent Activity</Header>}
            columnDefinitions={[
              {
                id: 'user',
                header: 'User',
                cell: (item) => item.user_display_name,
              },
              {
                id: 'action',
                header: 'Action',
                cell: (item) => (
                  <Box>
                    <Box variant="span" fontWeight="bold">{item.action}</Box>{' '}
                    {item.entity_type.replace('_', ' ')}
                  </Box>
                ),
              },
              {
                id: 'entity',
                header: 'Entity',
                cell: (item) => {
                  const routeMap: Record<string, string> = {
                    office: '/offices',
                    lease: '/leases',
                    maintenance_ticket: '/maintenance-tickets',
                    transition: '/transitions',
                    hvac_contract: '/hvac-contracts',
                    landlord: '/landlords',
                  };
                  const base = routeMap[item.entity_type] || '';
                  return item.action === 'deleted' ? (
                    <Box>{item.entity_label}</Box>
                  ) : (
                    <Link onFollow={() => navigate(`${base}/${item.entity_id}`)}>
                      {item.entity_label}
                    </Link>
                  );
                },
              },
              {
                id: 'time',
                header: 'Time',
                cell: (item) => {
                  const d = new Date(item.created_at);
                  const now = new Date();
                  const diffMs = now.getTime() - d.getTime();
                  const diffMin = Math.floor(diffMs / 60000);
                  if (diffMin < 1) return 'just now';
                  if (diffMin < 60) return `${diffMin}m ago`;
                  const diffHr = Math.floor(diffMin / 60);
                  if (diffHr < 24) return `${diffHr}h ago`;
                  return d.toLocaleDateString();
                },
              },
            ]}
            items={recentActivity}
            empty={
              <Box textAlign="center" color="text-body-secondary" padding="l">
                No recent activity
              </Box>
            }
            variant="embedded"
          />
        )}
      </SpaceBetween>

      <DashboardSettingsModal
        visible={settingsOpen}
        onDismiss={() => setSettingsOpen(false)}
        widgets={DASHBOARD_WIDGETS}
        widgetVisibility={widgetConfig}
      />
    </ContentLayout>
  );
};

export default DashboardPage;
