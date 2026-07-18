import axios from "axios"
import type {
  AdminOrg,
  AdminOrgDetail,
  AdminUser,
  AuditEntry,
  BillingDetail,
  BillingRow,
  ConsoleMe,
  DunningRow,
  FunnelStage,
  ImpersonateResponse,
  MrrTrendPoint,
  OrgMovementPoint,
  OrgPatch,
  OrgTimelineEntry,
  Paginated,
  PlatformMetrics,
  RevenueMetrics,
  TokenSpendPoint,
} from "../types"

const api = axios.create({ baseURL: "" })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("admin_token")
  if (token) config.headers.Authorization = "Be" + "arer " + token
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("admin_token")
      window.location.href = "/login"
    }
    return Promise.reject(err)
  },
)

export interface LoginResponse {
  access_token?: string
  token_type?: string
  mfa_required?: boolean
  mfa_setup_required?: boolean
  mfa_token?: string
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await api.post<LoginResponse>("/api/v1/auth/login", { email, password })
  return res.data
}

export async function mfaSetup(mfa_token: string): Promise<{ secret: string; qr_uri: string }> {
  const res = await api.post<{ secret: string; qr_uri: string }>("/api/v1/auth/mfa/setup", { mfa_token })
  return res.data
}

export async function mfaEnable(
  mfa_token: string,
  code: string,
): Promise<{ access_token: string; backup_codes: string[] }> {
  const res = await api.post<{ access_token: string; backup_codes: string[] }>(
    "/api/v1/auth/mfa/enable",
    { mfa_token, code },
  )
  return res.data
}

export async function mfaVerify(mfa_token: string, code: string): Promise<{ access_token: string }> {
  const res = await api.post<{ access_token: string }>("/api/v1/auth/mfa/verify", { mfa_token, code })
  return res.data
}

export async function getConsoleMe(): Promise<ConsoleMe> {
  const res = await api.get<ConsoleMe>("/admin/v1/users/me")
  return res.data
}

export async function getMetrics(): Promise<PlatformMetrics> {
  const res = await api.get<PlatformMetrics>("/admin/v1/metrics")
  return res.data
}

export async function getMrrTrend(): Promise<MrrTrendPoint[]> {
  const res = await api.get<MrrTrendPoint[]>("/admin/v1/metrics/mrr-trend")
  return res.data
}

export async function getNewVsChurned(): Promise<OrgMovementPoint[]> {
  const res = await api.get<OrgMovementPoint[]>("/admin/v1/metrics/new-vs-churned")
  return res.data
}

export async function getTokenSpendTrend(): Promise<TokenSpendPoint[]> {
  const res = await api.get<TokenSpendPoint[]>("/admin/v1/metrics/token-spend-trend")
  return res.data
}

export async function getTrialFunnel(): Promise<FunnelStage[]> {
  const res = await api.get<FunnelStage[]>("/admin/v1/metrics/trial-funnel")
  return res.data
}

export async function getScheduledJobs(): Promise<import("../types").ScheduledJobsResponse> {
  const res = await api.get<import("../types").ScheduledJobsResponse>("/admin/v1/metrics/jobs")
  return res.data
}

export async function getFeatureUsage(params: {
  months?: number
  org_id?: string
} = {}): Promise<import("../types").FeatureAdoptionResponse> {
  const res = await api.get<import("../types").FeatureAdoptionResponse>("/admin/v1/usage/features", { params })
  return res.data
}

export async function getPlatformTokens(params: {
  period?: string
  limit?: number
} = {}): Promise<import("../types").PlatformTokensResponse> {
  const res = await api.get<import("../types").PlatformTokensResponse>("/admin/v1/usage/tokens", { params })
  return res.data
}

export async function getOrgUsage(orgId: string): Promise<import("../types").OrgUsageResponse> {
  const res = await api.get<import("../types").OrgUsageResponse>(`/admin/v1/usage/orgs/${orgId}`)
  return res.data
}

export async function getOrgs(params: {
  page?: number
  page_size?: number
  search?: string
  plan?: string
  is_active?: boolean
  payment_status?: string
}): Promise<Paginated<AdminOrg>> {
  const res = await api.get<Paginated<AdminOrg>>("/admin/v1/orgs", { params })
  return res.data
}

export async function getOrg(orgId: string): Promise<AdminOrgDetail> {
  const res = await api.get<AdminOrgDetail>(`/admin/v1/orgs/${orgId}`)
  return res.data
}

export async function getOrgTimeline(orgId: string): Promise<OrgTimelineEntry[]> {
  const res = await api.get<OrgTimelineEntry[]>(`/admin/v1/orgs/${orgId}/timeline`)
  return res.data
}

export async function getOrgCatalog(orgId: string): Promise<import("../types").EntitlementsCatalog> {
  const res = await api.get<import("../types").EntitlementsCatalog>(`/admin/v1/orgs/${orgId}/catalog`)
  return res.data
}

export async function patchOrg(orgId: string, patch: OrgPatch): Promise<AdminOrgDetail> {
  const res = await api.patch<AdminOrgDetail>(`/admin/v1/orgs/${orgId}`, patch)
  return res.data
}

export async function impersonateOrg(orgId: string): Promise<ImpersonateResponse> {
  const res = await api.post<ImpersonateResponse>(`/admin/v1/orgs/${orgId}/impersonate`)
  return res.data
}

export async function bulkOrgAction(payload: {
  org_ids: string[]
  action: "suspend" | "change_plan" | "send_message"
  reason?: string
  plan?: string
  message?: string
}): Promise<{ action: string; updated_count: number; org_ids: string[] }> {
  const res = await api.post("/admin/v1/orgs/bulk-actions", payload)
  return res.data
}

export async function downloadOrgs(params: {
  search?: string
  plan?: string
  payment_status?: string
}): Promise<void> {
  const res = await api.get("/admin/v1/orgs/export", { params, responseType: "blob" })
  const url = URL.createObjectURL(res.data)
  const a = document.createElement("a")
  a.href = url
  a.download = "organizations.csv"
  a.click()
  URL.revokeObjectURL(url)
}

export async function getUsers(params: {
  page?: number
  page_size?: number
  search?: string
  org_id?: string
  role?: string
  is_active?: boolean
  is_super_admin?: boolean
}): Promise<Paginated<AdminUser>> {
  const res = await api.get<Paginated<AdminUser>>("/admin/v1/users", { params })
  return res.data
}

export async function patchUser(
  userId: string,
  patch: { is_active?: boolean; role?: string; is_super_admin?: boolean; organization_id?: string | null; console_role?: string | null },
): Promise<AdminUser> {
  const res = await api.patch<AdminUser>(`/admin/v1/users/${userId}`, patch)
  return res.data
}

export async function getBilling(params: {
  page?: number
  page_size?: number
  payment_status?: string
  plan?: string
}): Promise<Paginated<BillingRow>> {
  const res = await api.get<Paginated<BillingRow>>("/admin/v1/billing", { params })
  return res.data
}

export async function getDunningQueue(): Promise<DunningRow[]> {
  const res = await api.get<DunningRow[]>("/admin/v1/billing/dunning-queue")
  return res.data
}

export async function cancelSubscription(orgId: string): Promise<BillingRow> {
  const res = await api.post<BillingRow>(`/admin/v1/billing/${orgId}/cancel`)
  return res.data
}

export async function restoreSubscription(orgId: string): Promise<BillingRow> {
  const res = await api.post<BillingRow>(`/admin/v1/billing/${orgId}/restore`)
  return res.data
}

export async function getRevenue(params?: { window_days?: number; months?: number }): Promise<RevenueMetrics> {
  const res = await api.get<RevenueMetrics>("/admin/v1/metrics/revenue", { params })
  return res.data
}

export async function getBillingDetail(orgId: string): Promise<BillingDetail> {
  const res = await api.get<BillingDetail>(`/admin/v1/billing/${orgId}/detail`)
  return res.data
}

export async function issueCredit(orgId: string, amount_cents: number, reason?: string): Promise<{ id: string }> {
  const res = await api.post(`/admin/v1/billing/${orgId}/credit`, { amount_cents, reason })
  return res.data
}

export async function extendTrial(orgId: string, days: number): Promise<BillingRow> {
  const res = await api.post<BillingRow>(`/admin/v1/billing/${orgId}/extend-trial`, { days })
  return res.data
}

export async function getAudit(params: {
  page?: number
  page_size?: number
  org_id?: string
  user_id?: string
  action?: string
  entity_type?: string
  date_from?: string
  date_to?: string
}): Promise<Paginated<AuditEntry>> {
  const res = await api.get<Paginated<AuditEntry>>("/admin/v1/audit", { params })
  return res.data
}

export async function downloadAudit(params: {
  org_id?: string
  user_id?: string
  action?: string
  entity_type?: string
  date_from?: string
  date_to?: string
}): Promise<void> {
  const res = await api.get("/admin/v1/audit/export", { params, responseType: "blob" })
  const url = URL.createObjectURL(res.data)
  const a = document.createElement("a")
  a.href = url
  a.download = "audit_log.csv"
  a.click()
  URL.revokeObjectURL(url)
}

// ─── Support requests (cross-org queue) ─────────────────────────────────────

export async function getSupportRequests(params: {
  page?: number
  page_size?: number
  status?: string
  org_id?: string
}): Promise<import("../types").Paginated<import("../types").SupportRequestRow>> {
  const res = await api.get<import("../types").Paginated<import("../types").SupportRequestRow>>(
    "/admin/v1/support-requests",
    { params },
  )
  return res.data
}

export async function updateSupportRequestStatus(
  requestId: string,
  status: string,
): Promise<import("../types").SupportRequestRow> {
  const res = await api.patch<import("../types").SupportRequestRow>(
    `/admin/v1/support-requests/${requestId}`,
    { status },
  )
  return res.data
}

export async function getSupportMessages(
  requestId: string,
): Promise<import("../types").SupportMessageRow[]> {
  const res = await api.get<import("../types").SupportMessageRow[]>(
    `/admin/v1/support-requests/${requestId}/messages`,
  )
  return res.data
}

export async function replySupportRequest(
  requestId: string,
  body: string,
): Promise<import("../types").SupportMessageRow> {
  const res = await api.post<import("../types").SupportMessageRow>(
    `/admin/v1/support-requests/${requestId}/messages`,
    { body },
  )
  return res.data
}

// ─── Stripe integration credentials ─────────────────────────────────────────

export async function getStripeConfig(): Promise<import("../types").StripeConfig> {
  const res = await api.get<import("../types").StripeConfig>("/admin/v1/billing/stripe-config")
  return res.data
}

export async function saveStripeConfig(
  payload: import("../types").StripeConfigInput,
): Promise<import("../types").StripeConfig> {
  const res = await api.put<import("../types").StripeConfig>("/admin/v1/billing/stripe-config", payload)
  return res.data
}

export async function testStripeConfig(): Promise<{ ok: boolean; error: string | null }> {
  const res = await api.post<{ ok: boolean; error: string | null }>("/admin/v1/billing/stripe-config/test")
  return res.data
}

// ─── Enterprise activation codes ────────────────────────────────────────────

export async function getEnterpriseCodes(): Promise<import("../types").EnterpriseCode[]> {
  const res = await api.get<import("../types").EnterpriseCode[]>("/admin/v1/billing/enterprise-codes")
  return res.data
}

export async function createEnterpriseCode(
  payload: import("../types").EnterpriseCodeInput,
): Promise<import("../types").EnterpriseCode> {
  const res = await api.post<import("../types").EnterpriseCode>("/admin/v1/billing/enterprise-codes", payload)
  return res.data
}

export async function revokeEnterpriseCode(codeId: string): Promise<import("../types").EnterpriseCode> {
  const res = await api.post<import("../types").EnterpriseCode>(`/admin/v1/billing/enterprise-codes/${codeId}/revoke`)
  return res.data
}
