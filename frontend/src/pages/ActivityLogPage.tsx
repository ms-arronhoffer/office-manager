import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import Table from '@cloudscape-design/components/table';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import Select from '@cloudscape-design/components/select';
import Input from '@cloudscape-design/components/input';
import DatePicker from '@cloudscape-design/components/date-picker';
import FormField from '@cloudscape-design/components/form-field';
import Pagination from '@cloudscape-design/components/pagination';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import {
  activityLog as activityLogApi,
  type ActivityFacets,
  type ActivityReportFilters,
} from '@/api';
import type { ActivityLogEntry } from '@/types';

type SelectOption = { label: string; value: string };

const ALL_OPTION: SelectOption = { label: 'All', value: '' };

const PAGE_SIZE_OPTIONS: SelectOption[] = [
  { label: '25 per page', value: '25' },
  { label: '50 per page', value: '50' },
  { label: '100 per page', value: '100' },
  { label: '200 per page', value: '200' },
];

const ACTION_LABELS: Record<string, string> = {
  created: 'Created',
  updated: 'Updated',
  deleted: 'Deleted',
  status_changed: 'Status changed',
};

const ENTITY_LABELS: Record<string, string> = {
  office: 'Office',
  lease: 'Lease',
  landlord: 'Landlord',
  vendor: 'Vendor',
  transition: 'Transition',
  hvac_contract: 'HVAC Contract',
  maintenance_ticket: 'Maintenance Ticket',
};

const ENTITY_PATH: Record<string, string> = {
  office: 'offices',
  lease: 'leases',
  landlord: 'landlords',
  vendor: 'vendors',
  transition: 'transitions',
  hvac_contract: 'hvac-contracts',
  maintenance_ticket: 'maintenance-tickets',
};

function actionStatus(action: string): 'success' | 'info' | 'error' | 'warning' {
  switch (action) {
    case 'created':
      return 'success';
    case 'updated':
      return 'info';
    case 'deleted':
      return 'error';
    case 'status_changed':
      return 'warning';
    default:
      return 'info';
  }
}

/**
 * Convert a YYYY-MM-DD value from <DatePicker> to an ISO datetime appropriate for
 * the corresponding side of an inclusive range:
 *   - bound = 'start' -> 00:00:00 of that day in the user's local time.
 *   - bound = 'end'   -> 23:59:59 of that day in the user's local time.
 * Returns undefined for empty input so the parameter is omitted from the request.
 */
function toIsoBound(date: string, bound: 'start' | 'end'): string | undefined {
  if (!date) return undefined;
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return undefined;
  if (bound === 'end') d.setHours(23, 59, 59, 999);
  else d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

const ActivityLogPage: React.FC = () => {
  const navigate = useNavigate();

  // Filter state
  const [entityType, setEntityType] = useState<SelectOption>(ALL_OPTION);
  const [action, setAction] = useState<SelectOption>(ALL_OPTION);
  const [user, setUser] = useState<SelectOption>(ALL_OPTION);
  const [dateFrom, setDateFrom] = useState<string>('');
  const [dateTo, setDateTo] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [pageSize, setPageSize] = useState<SelectOption>(PAGE_SIZE_OPTIONS[1]);
  const [page, setPage] = useState<number>(1);

  // Data state
  const [items, setItems] = useState<ActivityLogEntry[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [totalPages, setTotalPages] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Filter facets
  const [facets, setFacets] = useState<ActivityFacets>({
    entity_types: [],
    actions: [],
    users: [],
  });

  useEffect(() => {
    let cancelled = false;
    activityLogApi
      .facets()
      .then((res) => {
        if (!cancelled) setFacets(res.data);
      })
      .catch(() => {
        // Non-fatal: dropdowns will fall back to a known default list below.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const entityTypeOptions = useMemo<SelectOption[]>(() => {
    const base = facets.entity_types.length
      ? facets.entity_types
      : Object.keys(ENTITY_LABELS);
    return [
      ALL_OPTION,
      ...base.map((v) => ({ label: ENTITY_LABELS[v] ?? v, value: v })),
    ];
  }, [facets.entity_types]);

  const actionOptions = useMemo<SelectOption[]>(() => {
    const base = facets.actions.length
      ? facets.actions
      : Object.keys(ACTION_LABELS);
    return [
      ALL_OPTION,
      ...base.map((v) => ({ label: ACTION_LABELS[v] ?? v, value: v })),
    ];
  }, [facets.actions]);

  const userOptions = useMemo<SelectOption[]>(
    () => [
      ALL_OPTION,
      ...facets.users.map((u) => ({ label: u.name, value: u.id })),
    ],
    [facets.users],
  );

  const buildParams = useCallback((): ActivityReportFilters => {
    return {
      entity_type: entityType.value || undefined,
      action: action.value || undefined,
      user_id: user.value || undefined,
      date_from: toIsoBound(dateFrom, 'start'),
      date_to: toIsoBound(dateTo, 'end'),
      search: search.trim() || undefined,
      page,
      page_size: parseInt(pageSize.value, 10),
    };
  }, [entityType, action, user, dateFrom, dateTo, search, page, pageSize]);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await activityLogApi.report(buildParams());
      setItems(res.data.items);
      setTotal(res.data.total);
      setTotalPages(res.data.total_pages || 0);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to load activity log.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  const handleClearFilters = () => {
    setEntityType(ALL_OPTION);
    setAction(ALL_OPTION);
    setUser(ALL_OPTION);
    setDateFrom('');
    setDateTo('');
    setSearch('');
    setPage(1);
  };

  const handleExport = async () => {
    setExporting(true);
    setError(null);
    try {
      const params = buildParams();
      // Drop pagination keys so the server returns the full filtered set.
      const { page: _p, page_size: _ps, ...exportParams } = params;
      const res = await activityLogApi.exportReport(exportParams);
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }));
      const link = document.createElement('a');
      link.href = url;
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
      link.download = `activity_log_${stamp}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      setError('Failed to export activity log.');
    } finally {
      setExporting(false);
    }
  };

  // Re-fetch when paging without re-evaluating the filters debounce path.
  const handlePageChange = (nextPage: number) => {
    setPage(nextPage);
  };

  const columnDefinitions = [
    {
      id: 'when',
      header: 'When',
      cell: (item: ActivityLogEntry) => new Date(item.created_at).toLocaleString(),
      width: 200,
    },
    {
      id: 'user',
      header: 'User',
      cell: (item: ActivityLogEntry) => item.user_display_name,
      width: 220,
    },
    {
      id: 'action',
      header: 'Action',
      cell: (item: ActivityLogEntry) => (
        <StatusIndicator type={actionStatus(item.action)}>
          {ACTION_LABELS[item.action] ?? item.action}
        </StatusIndicator>
      ),
      width: 160,
    },
    {
      id: 'entity_type',
      header: 'Type',
      cell: (item: ActivityLogEntry) => ENTITY_LABELS[item.entity_type] ?? item.entity_type,
      width: 180,
    },
    {
      id: 'entity_label',
      header: 'Entity',
      cell: (item: ActivityLogEntry) => {
        const path = ENTITY_PATH[item.entity_type];
        if (!path) return item.entity_label;
        return (
          <Link
            href={`/${path}/${item.entity_id}`}
            onFollow={(e) => {
              e.preventDefault();
              navigate(`/${path}/${item.entity_id}`);
            }}
          >
            {item.entity_label}
          </Link>
        );
      },
    },
    {
      id: 'changes',
      header: 'Changes',
      cell: (item: ActivityLogEntry) => {
        if (!item.changes) return '—';
        const keys = Object.keys(item.changes);
        if (keys.length === 0) return '—';
        return (
          <Box variant="small">
            {keys.map((k) => {
              const c = item.changes![k];
              const oldVal = c.old == null ? '∅' : String(c.old);
              const newVal = c.new == null ? '∅' : String(c.new);
              return (
                <div key={k}>
                  <strong>{k}:</strong> {oldVal} → {newVal}
                </div>
              );
            })}
          </Box>
        );
      },
    },
  ];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={fetchReport} iconName="refresh">
                Refresh
              </Button>
              <Button
                onClick={handleExport}
                loading={exporting}
                iconName="download"
                variant="primary"
              >
                Export CSV
              </Button>
            </SpaceBetween>
          }
          description="Filterable audit trail of every create / update / delete action across the system."
        >
          Audit Log Report
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Container header={<Header variant="h2">Filters</Header>}>
          <SpaceBetween size="m">
            <ColumnLayout columns={3}>
              <FormField label="Entity type">
                <Select
                  selectedOption={entityType}
                  onChange={({ detail }) => {
                    setEntityType(detail.selectedOption as SelectOption);
                    setPage(1);
                  }}
                  options={entityTypeOptions}
                />
              </FormField>
              <FormField label="Action">
                <Select
                  selectedOption={action}
                  onChange={({ detail }) => {
                    setAction(detail.selectedOption as SelectOption);
                    setPage(1);
                  }}
                  options={actionOptions}
                />
              </FormField>
              <FormField label="User">
                <Select
                  selectedOption={user}
                  onChange={({ detail }) => {
                    setUser(detail.selectedOption as SelectOption);
                    setPage(1);
                  }}
                  options={userOptions}
                  filteringType="auto"
                  empty="No users"
                />
              </FormField>
              <FormField label="From (date)">
                <DatePicker
                  value={dateFrom}
                  onChange={({ detail }) => {
                    setDateFrom(detail.value);
                    setPage(1);
                  }}
                  placeholder="YYYY/MM/DD"
                />
              </FormField>
              <FormField label="To (date)">
                <DatePicker
                  value={dateTo}
                  onChange={({ detail }) => {
                    setDateTo(detail.value);
                    setPage(1);
                  }}
                  placeholder="YYYY/MM/DD"
                />
              </FormField>
              <FormField
                label="Search"
                description="Substring match on entity label or user name."
              >
                <Input
                  value={search}
                  onChange={({ detail }) => {
                    setSearch(detail.value);
                  }}
                  onBlur={() => setPage(1)}
                  onKeyDown={({ detail }) => {
                    if (detail.key === 'Enter') {
                      setPage(1);
                      fetchReport();
                    }
                  }}
                  placeholder="e.g. Smith Building"
                />
              </FormField>
            </ColumnLayout>

            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => { setPage(1); fetchReport(); }} variant="primary">
                Apply
              </Button>
              <Button onClick={handleClearFilters}>Clear</Button>
            </SpaceBetween>
          </SpaceBetween>
        </Container>

        <Table
          columnDefinitions={columnDefinitions}
          items={items}
          loading={loading}
          loadingText="Loading audit log..."
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              No activity matches these filters.
            </Box>
          }
          header={
            <Header
              counter={`(${total})`}
              actions={
                <Select
                  selectedOption={pageSize}
                  onChange={({ detail }) => {
                    setPageSize(detail.selectedOption as SelectOption);
                    setPage(1);
                  }}
                  options={PAGE_SIZE_OPTIONS}
                />
              }
            >
              Results
            </Header>
          }
          pagination={
            <Pagination
              currentPageIndex={page}
              pagesCount={Math.max(1, totalPages)}
              onChange={({ detail }) => handlePageChange(detail.currentPageIndex)}
            />
          }
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default ActivityLogPage;
