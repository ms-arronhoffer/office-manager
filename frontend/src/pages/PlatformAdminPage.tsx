import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Grid from '@cloudscape-design/components/grid';
import Badge from '@cloudscape-design/components/badge';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import TextFilter from '@cloudscape-design/components/text-filter';
import Pagination from '@cloudscape-design/components/pagination';
import ButtonDropdown from '@cloudscape-design/components/button-dropdown';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';
import { useFlashbar } from '@/context/FlashbarContext';
import {
  superAdmin,
  type AdminOrg,
  type AdminUser,
  type PlatformMetrics,
  type ScheduledJob,
} from '@/api/superAdmin';

const usd = (cents: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(
    cents / 100,
  );

const KpiTile: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
  <Container>
    <Box variant="awsui-key-label">{label}</Box>
    <Box fontSize="display-l" fontWeight="bold" color={accent ? 'text-status-error' : undefined}>
      {value}
    </Box>
  </Container>
);

const OverviewTab: React.FC = () => {
  const [m, setM] = useState<PlatformMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    superAdmin
      .metrics()
      .then((r) => setM(r.data))
      .catch(() => setError('Failed to load platform metrics.'));
  }, []);

  if (error) return <StatusIndicator type="error">{error}</StatusIndicator>;
  if (!m) return <StatusIndicator type="loading">Loading metrics…</StatusIndicator>;

  return (
    <SpaceBetween size="l">
      <Grid gridDefinition={[{ colspan: 3 }, { colspan: 3 }, { colspan: 3 }, { colspan: 3 }]}>
        <KpiTile label="Organizations" value={`${m.total_orgs}`} />
        <KpiTile label="Active" value={`${m.active_orgs}`} />
        <KpiTile label="Trials" value={`${m.trial_orgs}`} />
        <KpiTile label="Past due" value={`${m.past_due_orgs}`} accent={m.past_due_orgs > 0} />
      </Grid>
      <Grid gridDefinition={[{ colspan: 3 }, { colspan: 3 }, { colspan: 3 }, { colspan: 3 }]}>
        <KpiTile label="Users" value={`${m.active_users}/${m.total_users}`} />
        <KpiTile label="Open tickets" value={`${m.open_tickets}`} />
        <KpiTile label={m.mrr_from_ledger ? 'MRR (ledger)' : 'MRR (est.)'} value={usd(m.mrr_cents)} />
        <KpiTile label="ARR" value={usd(m.arr_cents)} />
      </Grid>
      <Container header={<Header variant="h3">Plan mix</Header>}>
        <SpaceBetween direction="horizontal" size="m">
          <Badge>Starter: {m.orgs_by_plan.starter}</Badge>
          <Badge color="blue">Pro: {m.orgs_by_plan.pro}</Badge>
          <Badge color="green">Enterprise: {m.orgs_by_plan.enterprise}</Badge>
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h3">At-risk accounts</Header>}>
        <SpaceBetween direction="horizontal" size="m">
          <Badge color="red">Trial expiring 7d: {m.at_risk_trial_expiring}</Badge>
          <Badge color="red">Past due: {m.at_risk_past_due}</Badge>
          <Badge color="grey">Canceled: {m.at_risk_canceled}</Badge>
          <Badge color="grey">Inactive: {m.at_risk_inactive}</Badge>
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
};

const PAGE_SIZE = 25;

const OrganizationsTab: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [rows, setRows] = useState<AdminOrg[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    superAdmin
      .listOrgs({ page, page_size: PAGE_SIZE, search: filter || undefined })
      .then((r) => {
        setRows(r.data.items);
        setTotal(r.data.total);
      })
      .catch(() => addFlash({ type: 'error', content: 'Failed to load organizations.' }))
      .finally(() => setLoading(false));
  }, [page, filter, addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    try {
      await fn();
      addFlash({ type: 'success', content: `${label} succeeded.` });
      load();
    } catch {
      addFlash({ type: 'error', content: `${label} failed.` });
    }
  };

  const impersonate = async (org: AdminOrg) => {
    try {
      const { data } = await superAdmin.impersonate(org.id);
      localStorage.setItem('access_token', data.token);
      addFlash({ type: 'success', content: `Impersonating ${data.impersonated_user_email}.` });
      window.location.href = '/';
    } catch {
      addFlash({ type: 'error', content: 'Impersonation failed.' });
    }
  };

  return (
    <Table<AdminOrg>
      items={rows}
      loading={loading}
      trackBy="id"
      header={
        <Header counter={`(${total})`} variant="h2">
          Organizations
        </Header>
      }
      filter={
        <TextFilter
          filteringText={filter}
          filteringPlaceholder="Search organizations"
          onChange={({ detail }) => {
            setPage(1);
            setFilter(detail.filteringText);
          }}
        />
      }
      pagination={
        <Pagination
          currentPageIndex={page}
          pagesCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
          onChange={({ detail }) => setPage(detail.currentPageIndex)}
        />
      }
      columnDefinitions={[
        { id: 'name', header: 'Name', cell: (o) => o.name },
        { id: 'plan', header: 'Plan', cell: (o) => <Badge>{o.plan}</Badge> },
        {
          id: 'status',
          header: 'Status',
          cell: (o) => (
            <StatusIndicator type={o.is_active ? 'success' : 'stopped'}>{o.payment_status}</StatusIndicator>
          ),
        },
        { id: 'risk', header: 'Risk', cell: (o) => o.risk_label },
        { id: 'seats', header: 'Seats', cell: (o) => `${o.seat_count}${o.max_seats ? `/${o.max_seats}` : ''}` },
        { id: 'tickets', header: 'Tickets', cell: (o) => o.ticket_count },
        {
          id: 'actions',
          header: 'Actions',
          cell: (o) => (
            <ButtonDropdown
              expandToViewport
              items={[
                { id: 'extend', text: 'Extend trial 14d' },
                o.is_active
                  ? { id: 'cancel', text: 'Cancel subscription' }
                  : { id: 'restore', text: 'Restore subscription' },
                { id: 'impersonate', text: 'Impersonate admin' },
              ]}
              onItemClick={({ detail }) => {
                if (detail.id === 'extend') act('Extend trial', () => superAdmin.extendTrial(o.id, 14));
                if (detail.id === 'cancel') act('Cancel', () => superAdmin.cancelSubscription(o.id));
                if (detail.id === 'restore') act('Restore', () => superAdmin.restoreSubscription(o.id));
                if (detail.id === 'impersonate') impersonate(o);
              }}
            >
              Manage
            </ButtonDropdown>
          ),
        },
      ]}
      empty={<Box textAlign="center">No organizations.</Box>}
    />
  );
};

const UsersTab: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    superAdmin
      .listUsers({ page, page_size: PAGE_SIZE, search: filter || undefined })
      .then((r) => {
        setRows(r.data.items);
        setTotal(r.data.total);
      })
      .catch(() => addFlash({ type: 'error', content: 'Failed to load users.' }))
      .finally(() => setLoading(false));
  }, [page, filter, addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const patch = async (u: AdminUser, body: Partial<{ is_active: boolean; is_super_admin: boolean }>) => {
    try {
      await superAdmin.patchUser(u.id, body);
      addFlash({ type: 'success', content: 'User updated.' });
      load();
    } catch {
      addFlash({ type: 'error', content: 'Update failed.' });
    }
  };

  return (
    <Table<AdminUser>
      items={rows}
      loading={loading}
      trackBy="id"
      header={
        <Header counter={`(${total})`} variant="h2">
          Users
        </Header>
      }
      filter={
        <TextFilter
          filteringText={filter}
          filteringPlaceholder="Search by name or email"
          onChange={({ detail }) => {
            setPage(1);
            setFilter(detail.filteringText);
          }}
        />
      }
      pagination={
        <Pagination
          currentPageIndex={page}
          pagesCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
          onChange={({ detail }) => setPage(detail.currentPageIndex)}
        />
      }
      columnDefinitions={[
        { id: 'name', header: 'Name', cell: (u) => u.display_name },
        { id: 'email', header: 'Email', cell: (u) => u.email },
        { id: 'org', header: 'Organization', cell: (u) => u.organization_name ?? '—' },
        { id: 'role', header: 'Role', cell: (u) => <Badge>{u.role}</Badge> },
        {
          id: 'super',
          header: 'Super-admin',
          cell: (u) => (u.is_super_admin ? <Badge color="blue">yes</Badge> : '—'),
        },
        {
          id: 'active',
          header: 'Active',
          cell: (u) => <StatusIndicator type={u.is_active ? 'success' : 'stopped'}>{u.is_active ? 'active' : 'disabled'}</StatusIndicator>,
        },
        {
          id: 'actions',
          header: 'Actions',
          cell: (u) => (
            <ButtonDropdown
              expandToViewport
              items={[
                { id: 'toggle', text: u.is_active ? 'Disable' : 'Enable' },
                { id: 'super', text: u.is_super_admin ? 'Revoke super-admin' : 'Grant super-admin' },
              ]}
              onItemClick={({ detail }) => {
                if (detail.id === 'toggle') patch(u, { is_active: !u.is_active });
                if (detail.id === 'super') patch(u, { is_super_admin: !u.is_super_admin });
              }}
            >
              Manage
            </ButtonDropdown>
          ),
        },
      ]}
      empty={<Box textAlign="center">No users.</Box>}
    />
  );
};

const JobsTab: React.FC = () => {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [running, setRunning] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    superAdmin
      .jobs()
      .then((r) => {
        setJobs(r.data.jobs);
        setRunning(r.data.scheduler_running);
      })
      .catch(() => setError('Failed to load scheduler jobs.'));
  }, []);

  if (error) return <StatusIndicator type="error">{error}</StatusIndicator>;

  return (
    <Table<ScheduledJob>
      items={jobs}
      trackBy="job_id"
      header={
        <Header
          variant="h2"
          info={running === null ? null : <StatusIndicator type={running ? 'success' : 'stopped'}>{running ? 'running' : 'stopped'}</StatusIndicator>}
        >
          Scheduled jobs
        </Header>
      }
      columnDefinitions={[
        { id: 'id', header: 'Job', cell: (j) => j.job_id },
        { id: 'next', header: 'Next run', cell: (j) => j.next_run_at ?? '—' },
        {
          id: 'status',
          header: 'Last status',
          cell: (j) =>
            j.last_status ? (
              <StatusIndicator type={j.last_status === 'success' ? 'success' : 'error'}>
                {j.last_status}
              </StatusIndicator>
            ) : (
              '—'
            ),
        },
        { id: 'runs', header: 'Runs', cell: (j) => j.run_count },
        { id: 'fail', header: 'Failures', cell: (j) => j.failure_count },
        { id: 'err', header: 'Last error', cell: (j) => j.last_error ?? '—' },
      ]}
      empty={<Box textAlign="center">No jobs registered.</Box>}
    />
  );
};

/**
 * Platform super-admin console — surfaces the /admin/v1 API (metrics, orgs,
 * users, scheduler jobs) that previously had no frontend. Gated to
 * is_super_admin via SuperAdminGuard.
 */
const PlatformAdminPage: React.FC = () => {
  const tabs: TabbedPageTab[] = useMemo(
    () => [
      { id: 'overview', label: 'Overview', href: '/platform', content: <OverviewTab /> },
      { id: 'orgs', label: 'Organizations', href: '/platform/orgs', content: <OrganizationsTab /> },
      { id: 'users', label: 'Users', href: '/platform/users', content: <UsersTab /> },
      { id: 'jobs', label: 'Jobs', href: '/platform/jobs', content: <JobsTab /> },
    ],
    [],
  );

  return (
    <ContentLayout header={<Header variant="h1">Platform administration</Header>}>
      <TabbedPage ariaLabel="Platform administration" tabs={tabs} />
    </ContentLayout>
  );
};

export default PlatformAdminPage;
