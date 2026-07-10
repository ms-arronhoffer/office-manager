export type ConsoleRole = "super_admin" | "support" | "finance"

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface OrgTimelineEntry {
  source: string
  kind: string
  title: string
  description: string | null
  occurred_at: string
  meta: Record<string, unknown> | null
}

export interface AdminOrg {
  id: string
  name: string
  slug: string
  plan: string
  is_active: boolean
  payment_status: string
  max_seats: number | null
  seat_count: number
  ticket_count: number
  trial_ends_at: string | null
  created_at: string
  risk_label: string
  health_score: number
  health_band: "healthy" | "at_risk" | "critical"
}

export interface AdminOrgDetail extends AdminOrg {
  stripe_customer_id: string | null
  stripe_subscription_id: string | null
  onboarding_complete: boolean
  open_ticket_count: number
  admin_notes: string | null
  office_count: number
  entitlement_overrides: Record<string, number | boolean | null>
  plan_defaults: Record<string, number | boolean | null>
  effective_entitlements: Record<string, number | boolean | null>
  health_factors: Record<string, unknown>
  timeline: OrgTimelineEntry[]
}

export interface OrgPatch {
  name?: string
  plan?: string
  is_active?: boolean
  max_seats?: number | null
  payment_status?: string
  trial_ends_at?: string | null
  onboarding_complete?: boolean
  admin_notes?: string | null
  entitlement_overrides?: Record<string, number | boolean | null>
}

export interface EntitlementsCatalog {
  plans: string[]
  limit_keys: string[]
  feature_keys: string[]
  catalog: Record<string, Record<string, number | boolean | null>>
}

export interface ImpersonateResponse {
  token: string
  impersonated_user_id: string
  impersonated_user_email: string
}

export interface AdminUser {
  id: string
  email: string
  display_name: string
  role: string
  is_active: boolean
  is_super_admin: boolean
  console_role: ConsoleRole | null
  organization_id: string | null
  organization_name: string | null
  last_login_at: string | null
  created_at: string
}

export interface ConsoleMe {
  id: string
  email: string
  display_name: string
  role: string
  is_super_admin: boolean
  console_role: ConsoleRole
  permissions: {
    can_view_billing: boolean
    can_manage_billing: boolean
    can_impersonate: boolean
    can_suspend_orgs: boolean
    can_change_plans: boolean
    can_manage_users: boolean
    can_view_usage: boolean
    can_view_audit: boolean
  }
}

export interface PlatformMetrics {
  total_orgs: number
  active_orgs: number
  trial_orgs: number
  past_due_orgs: number
  new_orgs_30d: number
  orgs_by_plan: { starter: number; pro: number; enterprise: number }
  total_users: number
  active_users: number
  total_tickets: number
  open_tickets: number
  mrr_cents: number
  arr_cents: number
  mrr_from_ledger?: boolean
  at_risk_trial_expiring: number
  at_risk_past_due: number
  at_risk_canceled: number
  at_risk_inactive: number
}

export interface RevenueMetrics {
  mrr_cents: number
  arr_cents: number
  collected_cents: number
  refunded_cents: number
  failed_cents: number
  net_cents: number
  window_days: number
  plan_breakdown: { plan: string; count: number; mrr_cents: number }[]
  timeseries: { period: string; collected_cents: number }[]
}

export interface MrrTrendPoint {
  period: string
  mrr_cents: number
  arr_cents: number
}

export interface OrgMovementPoint {
  period: string
  new_orgs: number
  churned_orgs: number
}

export interface TokenSpendPoint {
  period: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_spend_cents: number
}

export interface FunnelStage {
  stage: string
  count: number
}

export interface FeatureAdoptionRow {
  feature: string
  label: string
  events: number
  org_count: number
  input_tokens: number
  output_tokens: number
  value_signal: number
  removal_candidate: boolean
}

export interface FeatureAdoptionResponse {
  months: number
  periods: string[]
  features: FeatureAdoptionRow[]
}

export interface TopTokenOrg {
  organization_id: string
  organization_name: string | null
  plan: string | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface PlatformTokensResponse {
  period: string
  input_tokens: number
  output_tokens: number
  total_tokens: number
  top_orgs: TopTokenOrg[]
}

export interface ScheduledJob {
  job_id: string
  next_run_at: string | null
  last_started_at: string | null
  last_finished_at: string | null
  last_status: string | null
  last_error: string | null
  last_duration_ms: number | null
  run_count: number
  failure_count: number
}

export interface ScheduledJobsResponse {
  scheduler_running: boolean
  jobs: ScheduledJob[]
}

export interface TokenWindow {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface OrgFeatureRow {
  feature: string
  label: string
  events: number
  input_tokens: number
  output_tokens: number
}

export interface OrgUsageResponse {
  organization_id: string
  period: string
  previous_period: string
  current: TokenWindow
  previous: TokenWindow
  input_token_limit: number | null
  output_token_limit: number | null
  by_feature: OrgFeatureRow[]
}

export interface BillingRow {
  id: string
  name: string
  plan: string
  payment_status: string
  is_active: boolean
  stripe_customer_id: string | null
  stripe_subscription_id: string | null
  max_seats: number | null
  seat_count: number
  trial_ends_at: string | null
  created_at: string
}

export interface BillingDetail {
  org_id: string
  name: string
  plan: string
  payment_status: string
  stripe_customer_id: string | null
  subscriptions: Record<string, unknown>[]
  invoices: Record<string, unknown>[]
  charges: Record<string, unknown>[]
  refunds: Record<string, unknown>[]
  credits: Record<string, unknown>[]
  credit_balance_cents: number
}

export interface DunningRow {
  id: string
  name: string
  plan: string
  payment_status: string
  past_due_since: string | null
  overdue_days: number
  seat_count: number
  trial_ends_at: string | null
  stripe_customer_id: string | null
}

export interface AuditEntry {
  id: string
  organization_id: string | null
  user_id: string
  user_display_name: string
  action: string
  entity_type: string
  entity_id: string
  entity_label: string | null
  changes: Record<string, unknown> | null
  created_at: string
}

export interface AuthPayload {
  sub: string
  role: string
  org_id: string | null
  is_super_admin: boolean
  console_role: ConsoleRole | null
  exp: number
}
