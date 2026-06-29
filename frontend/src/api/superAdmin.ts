import axios from 'axios';

// Super-admin endpoints are mounted under /admin/v1 (separate from the tenant
// /api/v1 base). They require a super-admin JWT, attached below from the same
// access_token used by the main client.
const adminClient = axios.create({ baseURL: '/admin/v1' });
adminClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = 'Bearer ' + token;
  }
  return config;
});

// ─── Types ───────────────────────────────────────────────────────────────────
export interface PlanBreakdown {
  starter: number;
  pro: number;
  enterprise: number;
}

export interface PlatformMetrics {
  total_orgs: number;
  active_orgs: number;
  trial_orgs: number;
  past_due_orgs: number;
  new_orgs_30d: number;
  orgs_by_plan?: PlanBreakdown;
  total_users: number;
  active_users: number;
  total_tickets: number;
  open_tickets: number;
  mrr_cents: number;
  arr_cents: number;
  mrr_from_ledger: boolean;
  at_risk_trial_expiring: number;
  at_risk_past_due: number;
  at_risk_canceled: number;
  at_risk_inactive: number;
}

export interface ScheduledJob {
  job_id: string;
  next_run_at: string | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_status: string | null;
  last_error: string | null;
  last_duration_ms: number | null;
  run_count: number;
  failure_count: number;
}

export interface ScheduledJobsResponse {
  scheduler_running: boolean;
  jobs: ScheduledJob[];
}

export interface AdminOrg {
  id: string;
  name: string;
  slug: string;
  plan: string;
  is_active: boolean;
  payment_status: string;
  max_seats: number | null;
  seat_count: number;
  ticket_count: number;
  trial_ends_at: string | null;
  created_at: string;
  risk_label: string;
}

export interface PaginatedOrgs {
  items: AdminOrg[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  is_super_admin: boolean;
  organization_id: string | null;
  organization_name: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface PaginatedUsers {
  items: AdminUser[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface OrgListParams {
  page?: number;
  page_size?: number;
  search?: string;
  plan?: string;
  is_active?: boolean;
  payment_status?: string;
}

interface UserListParams {
  page?: number;
  page_size?: number;
  search?: string;
  org_id?: string;
  role?: string;
  is_active?: boolean;
}

// ─── API ─────────────────────────────────────────────────────────────────────
export const superAdmin = {
  metrics: () => adminClient.get<PlatformMetrics>('/metrics'),

  jobs: () => adminClient.get<ScheduledJobsResponse>('/metrics/jobs'),

  listOrgs: (params: OrgListParams = {}) =>
    adminClient.get<PaginatedOrgs>('/orgs', { params }),

  patchOrg: (orgId: string, body: Partial<{ plan: string; is_active: boolean; payment_status: string }>) =>
    adminClient.patch<AdminOrg>(`/orgs/${orgId}`, body),

  extendTrial: (orgId: string, days: number) =>
    adminClient.post(`/billing/${orgId}/extend-trial`, { days }),

  cancelSubscription: (orgId: string) => adminClient.post(`/billing/${orgId}/cancel`),

  restoreSubscription: (orgId: string) => adminClient.post(`/billing/${orgId}/restore`),

  impersonate: (orgId: string) =>
    adminClient.post<{ token: string; impersonated_user_email: string }>(`/orgs/${orgId}/impersonate`),

  listUsers: (params: UserListParams = {}) =>
    adminClient.get<PaginatedUsers>('/users', { params }),

  patchUser: (
    userId: string,
    body: Partial<{ is_active: boolean; is_super_admin: boolean; role: string }>,
  ) => adminClient.patch<AdminUser>(`/users/${userId}`, body),
};

export default superAdmin;
