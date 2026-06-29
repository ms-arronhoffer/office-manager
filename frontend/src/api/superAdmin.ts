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

export interface RevenueMetrics {
  mrr_cents: number;
  arr_cents: number;
  collected_cents: number;
  refunded_cents: number;
  failed_cents: number;
  net_cents: number;
  window_days: number;
  plan_breakdown: Array<{ plan: string; count: number; mrr_cents: number }>;
  timeseries: Array<{ period: string; collected_cents: number }>;
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

export type EntitlementValue = number | boolean | null;

export interface AdminOrgDetail extends AdminOrg {
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  onboarding_complete: boolean;
  open_ticket_count: number;
  admin_notes: string | null;
  office_count: number;
  entitlement_overrides: Record<string, EntitlementValue>;
  plan_defaults: Record<string, EntitlementValue>;
  effective_entitlements: Record<string, EntitlementValue>;
}

export interface EntitlementsCatalog {
  plans: string[];
  limit_keys: string[];
  feature_keys: string[];
  catalog: Record<string, Record<string, EntitlementValue>>;
}

export interface OrgPatch {
  name?: string;
  plan?: string;
  is_active?: boolean;
  max_seats?: number | null;
  payment_status?: string;
  trial_ends_at?: string | null;
  onboarding_complete?: boolean;
  admin_notes?: string | null;
  entitlement_overrides?: Record<string, EntitlementValue>;
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

export interface BillingRow {
  id: string;
  name: string;
  plan: string;
  payment_status: string;
  is_active: boolean;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  max_seats: number | null;
  seat_count: number;
  trial_ends_at: string | null;
  created_at: string;
}

export interface PaginatedBilling {
  items: BillingRow[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface BillingDetail {
  org_id: string;
  name: string;
  plan: string;
  payment_status: string;
  stripe_customer_id: string | null;
  subscriptions: Record<string, unknown>[];
  invoices: Record<string, unknown>[];
  charges: Record<string, unknown>[];
  refunds: Record<string, unknown>[];
  credits: Record<string, unknown>[];
  credit_balance_cents: number;
}

export interface TopTokenOrg {
  organization_id: string;
  organization_name: string | null;
  plan: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface PlatformTokensResponse {
  period: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  top_orgs: TopTokenOrg[];
}

export interface FeatureAdoptionRow {
  feature: string;
  label: string;
  events: number;
  org_count: number;
  input_tokens: number;
  output_tokens: number;
  value_signal: number;
  removal_candidate: boolean;
}

export interface FeatureAdoptionResponse {
  months: number;
  periods: string[];
  features: FeatureAdoptionRow[];
}

export interface AuditEntry {
  id: string;
  organization_id: string | null;
  user_id: string;
  user_display_name: string;
  action: string;
  entity_type: string;
  entity_id: string;
  entity_label: string | null;
  changes: Record<string, unknown> | null;
  created_at: string;
}

export interface PaginatedAudit {
  items: AuditEntry[];
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

interface BillingListParams {
  page?: number;
  page_size?: number;
  payment_status?: string;
  plan?: string;
}

interface AuditListParams {
  page?: number;
  page_size?: number;
  org_id?: string;
  user_id?: string;
  action?: string;
  entity_type?: string;
  date_from?: string;
  date_to?: string;
}

// ─── API ─────────────────────────────────────────────────────────────────────
export const superAdmin = {
  metrics: () => adminClient.get<PlatformMetrics>('/metrics'),
  revenue: (params: { window_days?: number; months?: number } = {}) =>
    adminClient.get<RevenueMetrics>('/metrics/revenue', { params }),

  jobs: () => adminClient.get<ScheduledJobsResponse>('/metrics/jobs'),

  listOrgs: (params: OrgListParams = {}) =>
    adminClient.get<PaginatedOrgs>('/orgs', { params }),

  getOrg: (orgId: string) => adminClient.get<AdminOrgDetail>(`/orgs/${orgId}`),

  orgCatalog: (orgId: string) => adminClient.get<EntitlementsCatalog>(`/orgs/${orgId}/catalog`),

  patchOrg: (orgId: string, body: OrgPatch) =>
    adminClient.patch<AdminOrgDetail>(`/orgs/${orgId}`, body),

  deleteOrg: (orgId: string) => adminClient.delete(`/orgs/${orgId}`),

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

  listBilling: (params: BillingListParams = {}) =>
    adminClient.get<PaginatedBilling>('/billing', { params }),

  billingDetail: (orgId: string) => adminClient.get<BillingDetail>(`/billing/${orgId}/detail`),

  issueCredit: (orgId: string, amountCents: number, reason?: string) =>
    adminClient.post(`/billing/${orgId}/credit`, { amount_cents: amountCents, reason }),

  platformTokens: (params: { period?: string; limit?: number } = {}) =>
    adminClient.get<PlatformTokensResponse>('/usage/tokens', { params }),

  featureUsage: (params: { months?: number; org_id?: string } = {}) =>
    adminClient.get<FeatureAdoptionResponse>('/usage/features', { params }),

  listAudit: (params: AuditListParams = {}) =>
    adminClient.get<PaginatedAudit>('/audit', { params }),
};

export default superAdmin;
