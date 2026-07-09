import client from './client';
import type {
  User,
  TokenResponse,
  SignupRequest,
  SignupResponse,
  Office,
  OfficeCreate,
  OfficeUpdate,
  Lease,
  LeaseCreate,
  LeaseUpdate,
  LeaseNote,
  Landlord,
  LandlordCreate,
  LandlordUpdate,
  LandlordContact,
  Vendor,
  VendorCreate,
  VendorUpdate,
  ManagementCompany,
  ManagementCompanyCreate,
  ManagementCompanyUpdate,
  EntityContact,
  EntityContactCreate,
  EntityContactUpdate,
  Transition,
  TransitionCreate,
  TransitionUpdate,
  ChecklistItem,
  HeatPump,
  HeatPumpServiceLog,
  HvacIssue,
  PmTask,
  PmLog,
  Backflow,
  MaintenanceContract,
  HvacContract,
  HvacContractCreate,
  HvacContractUpdate,
  PaginatedResponse,
  DashboardSummary,
  LeaseExpirationByYear,
  ReportTemplate,
  ReportRequest,
  ReportPreviewResponse,
  Manager,
  ManagerCreate,
  Attachment,
  TicketCategory,
  TicketCategoryCreate,
  MaintenanceTicket,
  MaintenanceTicketCreate,
  MaintenanceTicketUpdate,
  ActivityLogEntry,
  SearchResult,
  AssistantResponse,
  UserPreferences,
  EmailReminderRule,
  EmailReminderRuleCreate,
  EmailLog,
  TicketTemplate,
  TicketTemplateCreate,
  TicketTemplateUpdate,
  RecurringTicketRule,
  RecurringTicketRuleCreate,
  RecurringTicketRuleUpdate,
  SlaAnalyticsResponse,
  LeaseAccountingResponse,
  LeasePortfolioResponse,
  LeaseRenewal,
  LeaseOption,
  LeaseAbstractResponse,
  AbstractClause,
  AbstractClauseUpdate,
  RentRollResponse,
  NotificationItem,
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  BillingSubscription,
  ApiKey,
  ApiKeyCreate,
  Webhook,
  WebhookCreate,
  WebhookUpdate,
  WebhookDelivery,
  BuildiumConnection,
  BuildiumConnectionInput,
  BuildiumTestConnectionResult,
  BuildiumEntityType,
  BuildiumGLAccountMapping,
  BuildiumMigrationRun,
  BuildiumMigrateRequest,
  TicketVolumeMonth,
  TopOfficeByTickets,
  LeaseRiskBucket,
  PortfolioHealthScore,
  OperatingExpense,
  OperatingExpenseCreate,
  OperatingExpenseUpdate,
  OperatingExpenseVariance,
  PortalTokenResponse,
  PortalTicket,
  PortalTicketUpdate,
  VendorPortalProfile,
  VendorPortalCOI,
  ClientPortalEntityType,
  ClientPortalInviteResponse,
  ClientPortalSession,
  ClientPortalProfile,
  ClientPortalStatus,
  ClientPortalChangeRequest,
  ClientPortalChangeRequestCreate,
  ClientPortalChangeRequestStatus,
  InsuranceCertificate,
  InsuranceCertificateCreate,
  InsuranceCertificateUpdate,
  InsuranceCertComplianceSummary,
  MaintenanceAsset,
  MaintenanceTask,
  MaintenanceLog,
  MaintenanceCatalog,
  MaintenanceCatalogCategory,
  MaintenanceCatalogSubtopic,
  MaintenanceOverview,
  MaintenanceCompliance,
  GenerateWorkOrderResult,
  WorkOrderCostLine,
  WorkOrderCostLineCreate,
  WorkOrderCostLineUpdate,
  WorkOrderCostSummary,
  CostPerSqftRow,
  MaintenanceSpendMonth,
  SpaceUtilizationRow,
  SpaceSnapshot,
  SpaceSnapshotCreate,
  GLAccount,
  GLAccountCreate,
  AccountingPeriod,
  JournalEntry,
  JournalEntryCreate,
  TrialBalanceRow,
  CamReconciliation,
  CamReconciliationCreate,
  CamReconciliationUpdate,
  CamReviewResponse,
  VendorBill,
  BillCreate,
  BillUpdate,
  PaymentCreate,
  Customer,
  CustomerCreate,
  CustomerUpdate,
  CustomerInvoice,
  InvoiceCreate,
  InvoiceUpdate,
  ReceiptCreate,
  ArAgingReport,
  BankAccount,
  BankAccountCreate,
  BankAccountUpdate,
  BankTransaction,
  BankTransactionCreate,
  BankImportResult,
  BankReconciliation,
  BankReconciliationCreate,
  ReconciliationReport,
  Vendor1099Summary,
  Vendor1099Detail,
  Budget,
  BudgetCreate,
  BudgetUpdate,
  BudgetReport,
  InspectionTemplate,
  InspectionTemplateCreate,
  InspectionTemplateUpdate,
  Inspection,
  InspectionCreate,
  InspectionUpdate,
  LifecycleEvent,
  LifecycleEventCreate,
  LifecycleEventUpdate,
  IncomeStatementResponse,
  BalanceSheetResponse,
  CashFlowStatementResponse,
  AuditReportResponse,
  PortalSession,
  ResidentPortalProfile,
  ResidentPortalLease,
  ResidentPortalBalance,
  ResidentPortalTicket,
  ResidentPortalMaintenanceCreate,
  ResidentPortalAnnouncement,
  OwnerPortalProfile,
  OwnerPortalProperty,
  OwnerPortalLedgerEntry,
  OwnerPortalBalance,
  OwnerPortalDistribution,
  OwnerPortalStatement,
} from '@/types';

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface LoginResponse {
  access_token?: string;
  token_type?: string;
  mfa_required?: boolean;
  mfa_setup_required?: boolean;
  mfa_token?: string;
}

export const auth = {
  login: (email: string, password: string) =>
    client.post<LoginResponse>('/auth/login', { email, password }),

  googleAuth: (token: string) =>
    client.post<LoginResponse>('/auth/google', { token }),

  register: (data: { email: string; display_name: string; password: string; role?: string }) =>
    client.post<User>('/auth/register', data),

  getMe: () => client.get<User>('/auth/me'),

  refreshToken: () => client.post<TokenResponse>('/auth/refresh'),

  changePassword: (currentPassword: string, newPassword: string) =>
    client.patch('/auth/me/password', { current_password: currentPassword, new_password: newPassword }),

  forgotPassword: (email: string) =>
    client.post('/auth/forgot-password', { email }),

  resetPassword: (token: string, new_password: string) =>
    client.post('/auth/reset-password', { token, new_password }),

  verifyMfa: (mfa_token: string, code: string) =>
    client.post<TokenResponse>('/auth/mfa/verify', { mfa_token, code }),
};

// ─── Managers ─────────────────────────────────────────────────────────────────
export const managers = {
  list: () => client.get<Manager[]>('/managers'),

  create: (data: ManagerCreate) => client.post<Manager>('/managers', data),

  update: (id: string, data: Partial<ManagerCreate>) => client.put<Manager>(`/managers/${id}`, data),

  delete: (id: string) => client.delete(`/managers/${id}`),
};

// ─── Offices ──────────────────────────────────────────────────────────────────
export const offices = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<Office>>('/offices', { params }),

  get: (id: string) => client.get<Office>(`/offices/${id}`),

  create: (data: OfficeCreate) => client.post<Office>('/offices', data),

  update: (id: string, data: OfficeUpdate) => client.put<Office>(`/offices/${id}`, data),

  delete: (id: string) => client.delete(`/offices/${id}`),

  restore: (id: string) => client.patch<Office>(`/offices/${id}/restore`),

  exportCsv: () =>
    client.get('/offices/export', { responseType: 'blob' }),

  getVendors: (officeId: string) =>
    client.get<Vendor[]>(`/offices/${officeId}/vendors`),

  getHvacContracts: (officeId: string) =>
    client.get<HvacContract[]>(`/offices/${officeId}/hvac-contracts`),
};

// ─── Leases ───────────────────────────────────────────────────────────────────
export const leases = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<Lease>>('/leases', { params }),

  get: (id: string) => client.get<Lease>(`/leases/${id}`),

  create: (data: LeaseCreate) => client.post<Lease>('/leases', data),

  update: (id: string, data: LeaseUpdate) => client.put<Lease>(`/leases/${id}`, data),

  delete: (id: string) => client.delete(`/leases/${id}`),

  restore: (id: string) => client.patch<Lease>(`/leases/${id}/restore`),

  clone: (id: string) => client.post<Lease>(`/leases/${id}/clone`),

  getUpcoming: (days = 90) =>
    client.get<Lease[]>('/leases/upcoming', { params: { days } }),

  getNoticesDue: () => client.get<Lease[]>('/leases/notices-due'),

  exportCsv: () => client.get('/leases/export', { responseType: 'blob' }),

  exportIcal: () => client.get('/leases/export/ical', { responseType: 'blob' }),

  addNote: (id: string, note_text: string) =>
    client.post<LeaseNote>(`/leases/${id}/notes`, { note_text }),

  deleteNote: (leaseId: string, noteId: string) =>
    client.delete(`/leases/${leaseId}/notes/${noteId}`),

  getAccounting: (id: string, includeJournalEntries = false) =>
    client.get<LeaseAccountingResponse>(`/leases/${id}/accounting`, {
      params: { include_journal_entries: includeJournalEntries },
    }),

  listRenewals: (leaseId: string) =>
    client.get<LeaseRenewal[]>(`/leases/${leaseId}/renewals`),

  createRenewal: (leaseId: string, data: { target_expiration?: string; new_rent_amount?: number; notes?: string }) =>
    client.post<LeaseRenewal>(`/leases/${leaseId}/renewals`, data),

  updateRenewal: (leaseId: string, renewalId: string, data: Partial<LeaseRenewal>) =>
    client.put<LeaseRenewal>(`/leases/${leaseId}/renewals/${renewalId}`, data),

  deleteRenewal: (leaseId: string, renewalId: string) =>
    client.delete(`/leases/${leaseId}/renewals/${renewalId}`),

  listOptions: (leaseId: string) =>
    client.get<LeaseOption[]>(`/leases/${leaseId}/options`),

  createOption: (leaseId: string, data: {
    option_type: string;
    exercise_window_start?: string;
    exercise_window_end?: string;
    notice_required_days?: number;
    new_term_months?: number;
    new_rent_amount?: number;
    notes?: string;
  }) =>
    client.post<LeaseOption>(`/leases/${leaseId}/options`, data),

  updateOption: (leaseId: string, optionId: string, data: Partial<LeaseOption>) =>
    client.put<LeaseOption>(`/leases/${leaseId}/options/${optionId}`, data),

  deleteOption: (leaseId: string, optionId: string) =>
    client.delete(`/leases/${leaseId}/options/${optionId}`),

  rentRoll: (params?: Record<string, unknown>) =>
    client.get<RentRollResponse>('/leases/rent-roll', { params }),

  getAbstract: (leaseId: string) =>
    client.get<LeaseAbstractResponse>(`/leases/${leaseId}/abstract`),

  updateAbstractClause: (leaseId: string, categoryKey: string, data: AbstractClauseUpdate) =>
    client.put<AbstractClause>(`/leases/${leaseId}/abstract/${categoryKey}`, data),
};

// ─── Landlords ────────────────────────────────────────────────────────────────
export const landlords = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<Landlord>>('/landlords', { params }),

  get: (id: string) => client.get<Landlord>(`/landlords/${id}`),

  create: (data: LandlordCreate) => client.post<Landlord>('/landlords', data),

  update: (id: string, data: LandlordUpdate) => client.put<Landlord>(`/landlords/${id}`, data),

  delete: (id: string) => client.delete(`/landlords/${id}`),

  restore: (id: string) => client.patch<Landlord>(`/landlords/${id}/restore`),

  addContact: (landlordId: string, data: { contact_name: string; title?: string; contact_type?: string; is_primary?: boolean; email?: string; phone?: string; notes?: string }) =>
    client.post<LandlordContact>(`/landlords/${landlordId}/contacts`, data),

  updateContact: (landlordId: string, contactId: string, data: Partial<LandlordContact>) =>
    client.put<LandlordContact>(`/landlords/${landlordId}/contacts/${contactId}`, data),

  deleteContact: (landlordId: string, contactId: string) =>
    client.delete(`/landlords/${landlordId}/contacts/${contactId}`),

  exportCsv: () => client.get('/landlords/export', { responseType: 'blob' }),
};

// ─── Vendors ─────────────────────────────────────────────────────────────────
export const vendors = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<Vendor>>('/vendors', { params }),

  get: (id: string) => client.get<Vendor>(`/vendors/${id}`),

  create: (data: VendorCreate) => client.post<Vendor>('/vendors', data),

  update: (id: string, data: VendorUpdate) => client.put<Vendor>(`/vendors/${id}`, data),

  delete: (id: string) => client.delete(`/vendors/${id}`),

  restore: (id: string) => client.patch<Vendor>(`/vendors/${id}/restore`),

  exportCsv: () => client.get('/vendors/export', { responseType: 'blob' }),
};

// ─── Management Companies ─────────────────────────────────────────────────────
export const managementCompanies = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<ManagementCompany>>('/management-companies', { params }),

  get: (id: string) => client.get<ManagementCompany>(`/management-companies/${id}`),

  create: (data: ManagementCompanyCreate) =>
    client.post<ManagementCompany>('/management-companies', data),

  update: (id: string, data: ManagementCompanyUpdate) =>
    client.put<ManagementCompany>(`/management-companies/${id}`, data),

  delete: (id: string) => client.delete(`/management-companies/${id}`),

  restore: (id: string) => client.patch<ManagementCompany>(`/management-companies/${id}/restore`),
};

// ─── Contacts (reusable across entities) ──────────────────────────────────────
export const contacts = {
  list: (entityType: string, entityId: string) =>
    client.get<EntityContact[]>('/contacts', {
      params: { entity_type: entityType, entity_id: entityId },
    }),

  create: (data: EntityContactCreate) => client.post<EntityContact>('/contacts', data),

  update: (id: string, data: EntityContactUpdate) =>
    client.put<EntityContact>(`/contacts/${id}`, data),

  delete: (id: string) => client.delete(`/contacts/${id}`),
};

// ─── Transitions ──────────────────────────────────────────────────────────────
export const transitions = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<Transition>>('/transitions', { params }),

  get: (id: string) => client.get<Transition>(`/transitions/${id}`),

  create: (data: TransitionCreate) => client.post<Transition>('/transitions', data),

  update: (id: string, data: TransitionUpdate) =>
    client.put<Transition>(`/transitions/${id}`, data),

  delete: (id: string) => client.delete(`/transitions/${id}`),

  restore: (id: string) => client.patch<Transition>(`/transitions/${id}/restore`),

  exportCsv: () => client.get('/transitions/export', { responseType: 'blob' }),

  addChecklistItem: (transitionId: string, item_label: string, sort_order?: number) =>
    client.post<ChecklistItem>(`/transitions/${transitionId}/checklist`, { item_label, sort_order }),

  updateChecklistItem: (transitionId: string, itemId: string, data: Partial<ChecklistItem>) =>
    client.put<ChecklistItem>(`/transitions/${transitionId}/checklist/${itemId}`, data),

  toggleChecklistItem: (transitionId: string, itemId: string) =>
    client.patch<ChecklistItem>(`/transitions/${transitionId}/checklist/${itemId}/toggle`),
};

// ─── HQ HVAC ──────────────────────────────────────────────────────────────────
export const hqHvac = {
  getHeatPumps: () => client.get<HeatPump[]>('/hq-hvac/heat-pumps'),

  getHeatPump: (id: string) => client.get<HeatPump>(`/hq-hvac/heat-pumps/${id}`),

  createHeatPump: (data: { unit_id: string; location_desc?: string; make?: string; model?: string; serial_number?: string; install_year?: number; notes?: string }) =>
    client.post<HeatPump>('/hq-hvac/heat-pumps', data),

  updateHeatPump: (id: string, data: Partial<HeatPump>) =>
    client.put<HeatPump>(`/hq-hvac/heat-pumps/${id}`, data),

  deleteHeatPump: (id: string) => client.delete(`/hq-hvac/heat-pumps/${id}`),

  addServiceLog: (pumpId: string, data: { service_date?: string; invoice_number?: string; cost?: number; description: string }) =>
    client.post<HeatPumpServiceLog>(`/hq-hvac/heat-pumps/${pumpId}/service-log`, data),

  getIssues: () => client.get<HvacIssue[]>('/hq-hvac/issues'),

  createIssue: (data: Partial<HvacIssue>) =>
    client.post<HvacIssue>('/hq-hvac/issues', data),

  updateIssue: (id: string, data: Partial<HvacIssue>) =>
    client.put<HvacIssue>(`/hq-hvac/issues/${id}`, data),

  deleteIssue: (id: string) => client.delete(`/hq-hvac/issues/${id}`),

  getPmTasks: () => client.get<PmTask[]>('/hq-hvac/pm-tasks'),

  createPmTask: (data: Partial<PmTask>) => client.post<PmTask>('/hq-hvac/pm-tasks', data),

  updatePmTask: (id: string, data: Partial<PmTask>) =>
    client.put<PmTask>(`/hq-hvac/pm-tasks/${id}`, data),

  deletePmTask: (id: string) => client.delete(`/hq-hvac/pm-tasks/${id}`),

  getPmLog: () => client.get<PmLog[]>('/hq-hvac/pm-log'),

  createPmLog: (data: Partial<PmLog>) =>
    client.post<PmLog>('/hq-hvac/pm-log', data),

  updatePmLog: (id: string, data: Partial<PmLog>) =>
    client.put<PmLog>(`/hq-hvac/pm-log/${id}`, data),

  deletePmLog: (id: string) => client.delete(`/hq-hvac/pm-log/${id}`),

  getBackflows: () => client.get<Backflow[]>('/hq-hvac/backflows'),

  createBackflow: (data: Partial<Backflow>) => client.post<Backflow>('/hq-hvac/backflows', data),

  updateBackflow: (id: string, data: Partial<Backflow>) =>
    client.put<Backflow>(`/hq-hvac/backflows/${id}`, data),

  deleteBackflow: (id: string) => client.delete(`/hq-hvac/backflows/${id}`),

  getMaintenanceContracts: () =>
    client.get<MaintenanceContract[]>('/hq-hvac/maintenance-contracts'),

  createMaintenanceContract: (data: Partial<MaintenanceContract>) =>
    client.post<MaintenanceContract>('/hq-hvac/maintenance-contracts', data),

  updateMaintenanceContract: (id: string, data: Partial<MaintenanceContract>) =>
    client.put<MaintenanceContract>(`/hq-hvac/maintenance-contracts/${id}`, data),

  deleteMaintenanceContract: (id: string) => client.delete(`/hq-hvac/maintenance-contracts/${id}`),
};

// ─── HVAC Contracts ───────────────────────────────────────────────────────────
export const hvacContracts = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<HvacContract>>('/hvac-contracts', { params }),

  get: (id: string) => client.get<HvacContract>(`/hvac-contracts/${id}`),

  create: (data: HvacContractCreate) => client.post<HvacContract>('/hvac-contracts', data),

  update: (id: string, data: HvacContractUpdate) =>
    client.put<HvacContract>(`/hvac-contracts/${id}`, data),

  delete: (id: string) => client.delete(`/hvac-contracts/${id}`),

  restore: (id: string) => client.patch<HvacContract>(`/hvac-contracts/${id}/restore`),

  getDue: (days = 30) =>
    client.get<HvacContract[]>('/hvac-contracts/due', { params: { days } }),

  exportCsv: () => client.get('/hvac-contracts/export', { responseType: 'blob' }),

  exportIcal: () => client.get('/hvac-contracts/export/ical', { responseType: 'blob' }),
};

// ─── Dashboard ────────────────────────────────────────────────────────────────
export const dashboard = {
  getSummary: () => client.get<DashboardSummary>('/dashboard/summary'),

  getLeaseExpirations: () =>
    client.get<LeaseExpirationByYear[]>('/dashboard/lease-expirations'),

  getHvacDue: () => client.get<HvacContract[]>('/dashboard/hvac-due'),

  getActiveTransitions: () => client.get<Transition[]>('/dashboard/active-transitions'),

  getTicketVolumeTrend: (months?: number) =>
    client.get<TicketVolumeMonth[]>('/dashboard/ticket-volume-trend', { params: { months } }),

  getTopOfficesByTickets: (limit?: number) =>
    client.get<TopOfficeByTickets[]>('/dashboard/top-offices-by-tickets', { params: { limit } }),

  getLeaseRisk: () => client.get<LeaseRiskBucket[]>('/dashboard/lease-risk'),

  getPortfolioHealth: () => client.get<PortfolioHealthScore>('/dashboard/portfolio-health'),

  getCostPerSqft: () => client.get<CostPerSqftRow[]>('/dashboard/cost-per-sqft'),

  getMaintenanceSpend: (months?: number) =>
    client.get<MaintenanceSpendMonth[]>('/dashboard/maintenance-spend', { params: { months } }),

  getSpaceUtilization: () => client.get<SpaceUtilizationRow[]>('/dashboard/space-utilization'),
};

// ─── Space Management ─────────────────────────────────────────────────────────
export const space = {
  listHistory: (officeId: string) =>
    client.get<SpaceSnapshot[]>(`/offices/${officeId}/space-history`),

  createSnapshot: (officeId: string, data: SpaceSnapshotCreate) =>
    client.post<SpaceSnapshot>(`/offices/${officeId}/space-history`, data),

  deleteSnapshot: (officeId: string, snapshotId: string) =>
    client.delete(`/offices/${officeId}/space-history/${snapshotId}`),
};

// ─── Reports ──────────────────────────────────────────────────────────────────
export const reports = {
  getTemplates: () => client.get<ReportTemplate[]>('/reports/templates'),

  preview: (data: { dataset: string; columns?: string[]; filters?: Record<string, unknown> }) =>
    client.post<ReportPreviewResponse>('/reports/preview', data),

  generate: (data: ReportRequest) =>
    client.post('/reports/generate', data, { responseType: 'blob' }),

  emailReport: (data: { dataset: string; columns?: string[]; filters?: Record<string, unknown>; recipients: string[]; html_body: string }) =>
    client.post<{ results: { recipient: string; sent: boolean }[] }>('/reports/email', data),

  hvacCostAnalytics: () =>
    client.get<{ year: number; total_cost: number; issue_count: number }[]>('/reports/analytics/hvac-costs'),

  ticketResolutionAnalytics: () =>
    client.get<{
      by_priority: { label: string; avg_days: number; count: number }[];
      by_category: { label: string; avg_days: number; count: number }[];
    }>('/reports/analytics/ticket-resolution'),

  slaAnalytics: () =>
    client.get<SlaAnalyticsResponse>('/reports/analytics/sla'),

  leaseAccountingPortfolio: () =>
    client.get<LeasePortfolioResponse>('/reports/lease-accounting-portfolio'),

  exportAmortizationCsv: (leaseId: string) =>
    client.get(`/reports/accounting/amortization/${leaseId}`, { responseType: 'blob' }),

  exportMaturityCsv: () =>
    client.get('/reports/accounting/maturity', { responseType: 'blob' }),
};

// ─── Attachments ──────────────────────────────────────────────────────────
export interface UploadLimits {
  max_file_size_mb: number;
  max_file_size_bytes: number;
  allowed_extensions: string[];
  allowed_entity_types: string[];
}

export const attachments = {
  list: (entityType: string, entityId: string) =>
    client.get<Attachment[]>(`/${entityType}/${entityId}/attachments`),

  upload: (
    entityType: string,
    entityId: string,
    file: File,
    description?: string,
    onProgress?: (loaded: number, total: number) => void,
  ) => {
    const formData = new FormData();
    formData.append('file', file);
    if (description) formData.append('description', description);
    return client.post<Attachment>(`/${entityType}/${entityId}/attachments`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (evt) => {
        if (onProgress && evt.total) onProgress(evt.loaded, evt.total);
      },
    });
  },

  download: (attachmentId: string) =>
    client.get(`/attachments/${attachmentId}/download`, { responseType: 'blob' }),

  delete: (attachmentId: string) =>
    client.delete(`/attachments/${attachmentId}`),

  getLimits: () => client.get<UploadLimits>('/attachments/limits'),

  getCounts: (entityType: string, ids: string[]) =>
    client.get<Record<string, number>>('/attachments/counts', {
      params: { entity_type: entityType, ids: ids.join(',') },
    }),
};

// ─── Users ────────────────────────────────────────────────────────────────────
export const users = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<User>>('/users', { params }),

  create: (data: { email: string; display_name: string; password: string; role?: string }) =>
    client.post<User>('/users', data),

  update: (id: string, data: Partial<User>) => client.put<User>(`/users/${id}`, data),

  delete: (id: string) => client.delete(`/users/${id}`),
};

// ─── Ticket Categories ───────────────────────────────────────────────────────
export const ticketCategories = {
  list: () => client.get<TicketCategory[]>('/ticket-categories'),

  create: (data: TicketCategoryCreate) =>
    client.post<TicketCategory>('/ticket-categories', data),

  delete: (id: string) => client.delete(`/ticket-categories/${id}`),
};

// ─── Maintenance Tickets ─────────────────────────────────────────────────────
export const maintenanceTickets = {
  list: (params?: Record<string, unknown>) =>
    client.get<PaginatedResponse<MaintenanceTicket>>('/maintenance-tickets', { params }),

  get: (id: string) => client.get<MaintenanceTicket>(`/maintenance-tickets/${id}`),

  create: (data: MaintenanceTicketCreate) =>
    client.post<MaintenanceTicket>('/maintenance-tickets', data),

  update: (id: string, data: MaintenanceTicketUpdate) =>
    client.put<MaintenanceTicket>(`/maintenance-tickets/${id}`, data),

  delete: (id: string) => client.delete(`/maintenance-tickets/${id}`),

  restore: (id: string) => client.patch<MaintenanceTicket>(`/maintenance-tickets/${id}/restore`),

  bulkUpdate: (data: { ids: string[]; status?: string; assigned_to_id?: string }) =>
    client.patch<MaintenanceTicket[]>('/maintenance-tickets/bulk', data),

  exportCsv: () => client.get('/maintenance-tickets/export', { responseType: 'blob' }),

  addNote: (id: string, noteText: string) =>
    client.post(`/maintenance-tickets/${id}/notes`, { note_text: noteText }),

  deleteNote: (id: string, noteId: string) =>
    client.delete(`/maintenance-tickets/${id}/notes/${noteId}`),

  getCostLines: (ticketId: string) =>
    client.get<WorkOrderCostSummary>(`/maintenance-tickets/${ticketId}/cost-lines`),

  createCostLine: (ticketId: string, data: WorkOrderCostLineCreate) =>
    client.post<WorkOrderCostLine>(`/maintenance-tickets/${ticketId}/cost-lines`, data),

  updateCostLine: (ticketId: string, lineId: string, data: WorkOrderCostLineUpdate) =>
    client.patch<WorkOrderCostLine>(`/maintenance-tickets/${ticketId}/cost-lines/${lineId}`, data),

  deleteCostLine: (ticketId: string, lineId: string) =>
    client.delete(`/maintenance-tickets/${ticketId}/cost-lines/${lineId}`),
};

// ─── Activity Log ───────────────────────────────────────────────────────────
export interface ActivityReportFilters {
  entity_type?: string;
  entity_id?: string;
  action?: string;
  user_id?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

export interface ActivityFacets {
  entity_types: string[];
  actions: string[];
  users: { id: string; name: string }[];
}

export const activityLog = {
  recent: (limit = 10) =>
    client.get<ActivityLogEntry[]>('/activity-log/recent', { params: { limit } }),

  list: (params?: { entity_type?: string; entity_id?: string; limit?: number }) =>
    client.get<ActivityLogEntry[]>('/activity-log', { params }),

  report: (params?: ActivityReportFilters) =>
    client.get<PaginatedResponse<ActivityLogEntry>>('/activity-log/report', { params }),

  exportReport: (params?: Omit<ActivityReportFilters, 'page' | 'page_size'>) =>
    client.get('/activity-log/report/export', { params, responseType: 'blob' }),

  facets: () => client.get<ActivityFacets>('/activity-log/report/facets'),
};

// ─── Search ─────────────────────────────────────────────────────────────────
export const search = {
  query: (q: string, limit = 10) =>
    client.get<SearchResult[]>('/search', { params: { q, limit } }),
};

// ─── In-app assistant (search-to-action) ────────────────────────────────────
export const assistant = {
  ask: (prompt: string) =>
    client.post<AssistantResponse>('/assistant', { prompt }),
};

// ─── User Preferences ──────────────────────────────────────────────────────
export const preferences = {
  get: () => client.get<UserPreferences>('/users/me/preferences'),
  update: (data: UserPreferences) => client.put<UserPreferences>('/users/me/preferences', data),
};


// ─── Email Rules ─────────────────────────────────────────────────────────────
// Backend mounts these routes at `/api/v1/email-rules` with each route's
// path declared as `/`, so the canonical URL has a trailing slash. Always
// use the trailing-slash form to avoid the 307-redirect dance (which can
// drop the request body / auth headers when the API is behind nginx).
export const emailRules = {
  list: () => client.get<EmailReminderRule[]>('/email-rules/'),

  getTypes: () =>
    client.get<{ value: string; label: string }[]>('/email-rules/types'),

  create: (data: EmailReminderRuleCreate) =>
    client.post<EmailReminderRule>('/email-rules/', data),

  update: (id: string, data: Partial<EmailReminderRuleCreate>) =>
    client.put<EmailReminderRule>(`/email-rules/${id}`, data),

  delete: (id: string) => client.delete(`/email-rules/${id}`),

  getLogs: (limit = 100) =>
    client.get<EmailLog[]>('/email-rules/logs', { params: { limit } }),

  testSend: (id: string) =>
    client.post<{ sent_to: string[]; failed: string[]; message?: string }>(`/email-rules/${id}/test`),
};

// ─── Imports ──────────────────────────────────────────────────────────────────
export const imports = {
  downloadTemplate: (entity: string) =>
    client.get(`/imports/${entity}/template`, { responseType: 'blob' }),

  upload: (entity: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post<{ created: number; updated: number; skipped: number; errors: string[] }>(
      `/imports/${entity}/import`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
  },
};

// ─── Admin: Trash ────────────────────────────────────────────────────────────
export interface TrashItem {
  id: string;
  entity_type: string;
  label: string;
  deleted_at: string | null;
}

export interface TrashSummary {
  counts: Record<string, number>;
  supported_types: string[];
}

export const trash = {
  summary: () => client.get<TrashSummary>('/admin/trash'),

  list: (entityType: string) =>
    client.get<{ entity_type: string; items: TrashItem[] }>('/admin/trash', {
      params: { entity_type: entityType },
    }),

  permanentDelete: (entityType: string, id: string) =>
    client.delete(`/admin/trash/${entityType}/${id}/permanent`),
};

// ─── Site Settings ────────────────────────────────────────────────────────────
export interface SiteSettings {
  app_name: string;
  login_subtitle: string;
  login_form_header: string;
  login_form_description: string;
  sla_high_days: number;
  sla_medium_days: number;
  sla_low_days: number;
}

export const siteSettings = {
  get: () => client.get<SiteSettings>('/site-settings'),
  update: (data: SiteSettings) => client.put<SiteSettings>('/site-settings', data),
};

// ─── Support Requests ─────────────────────────────────────────────────────────
export interface SupportRequest {
  id: string;
  subject: string;
  message: string;
  status: 'open' | 'resolved';
  requester_user_id: string | null;
  requester_name: string | null;
  requester_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface SupportEmailResult {
  sent: boolean;
  support_email: string | null;
  detail: string;
}

export interface SupportConfig {
  support_email: string | null;
}

export const supportRequests = {
  create: (data: { subject: string; message: string }) =>
    client.post<SupportRequest>('/support-requests', data),
  list: (params?: { status?: string }) =>
    client.get<SupportRequest[]>('/support-requests', { params }),
  getConfig: () => client.get<SupportConfig>('/support-requests/config'),
  updateStatus: (id: string, status: 'open' | 'resolved') =>
    client.patch<SupportRequest>(`/support-requests/${id}`, { status }),
  email: (id: string) =>
    client.post<SupportEmailResult>(`/support-requests/${id}/email`),
  remove: (id: string) => client.delete(`/support-requests/${id}`),
};

// ─── Ticket Templates ─────────────────────────────────────────────────────────
export const ticketTemplates = {
  list: () => client.get<TicketTemplate[]>('/ticket-templates'),

  create: (data: TicketTemplateCreate) =>
    client.post<TicketTemplate>('/ticket-templates', data),

  update: (id: string, data: TicketTemplateUpdate) =>
    client.put<TicketTemplate>(`/ticket-templates/${id}`, data),

  delete: (id: string) => client.delete(`/ticket-templates/${id}`),

  bulkCreate: (templateId: string, officeIds: string[]) =>
    client.post<{ created: number; ticket_ids: string[] }>(
      `/ticket-templates/${templateId}/bulk-create`,
      { office_ids: officeIds },
    ),
};

// ─── Notifications ────────────────────────────────────────────────────────────
export const notifications = {
  list: () => client.get<NotificationItem[]>('/notifications'),

  count: () => client.get<{ unread: number }>('/notifications/count'),

  markRead: (id: string) => client.patch(`/notifications/${id}/read`),

  markAllRead: () => client.patch('/notifications/read-all'),

  delete: (id: string) => client.delete(`/notifications/${id}`),
};

// ─── Recurring Ticket Rules ───────────────────────────────────────────────────
export const recurringTicketRules = {
  list: () => client.get<RecurringTicketRule[]>('/recurring-ticket-rules'),

  create: (data: RecurringTicketRuleCreate) =>
    client.post<RecurringTicketRule>('/recurring-ticket-rules', data),

  update: (id: string, data: RecurringTicketRuleUpdate) =>
    client.put<RecurringTicketRule>(`/recurring-ticket-rules/${id}`, data),

  toggle: (id: string) =>
    client.patch<RecurringTicketRule>(`/recurring-ticket-rules/${id}/toggle`),

  delete: (id: string) => client.delete(`/recurring-ticket-rules/${id}`),
};

// ─── Billing ──────────────────────────────────────────────────────────────────
export const billing = {
  getSubscription: () => client.get<BillingSubscription>('/billing/subscription'),

  createCheckout: (plan: 'pro' | 'enterprise') =>
    client.post<{ checkout_url: string }>('/billing/checkout', { plan }),

  createPortal: () =>
    client.post<{ portal_url: string }>('/billing/portal'),
};

// ─── API Keys ─────────────────────────────────────────────────────────────────
export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export const apiKeys = {
  list: () => client.get<ApiKey[]>('/api-keys'),

  create: (data: ApiKeyCreate) => client.post<ApiKeyCreated>('/api-keys', data),

  update: (id: string, data: { name?: string; scopes?: string[]; is_active?: boolean }) =>
    client.patch<ApiKey>(`/api-keys/${id}`, data),

  revoke: (id: string) => client.delete(`/api-keys/${id}`),
};

export const webhooks = {
  list: () => client.get<Webhook[]>('/webhooks'),

  create: (data: WebhookCreate) => client.post<Webhook>('/webhooks', data),

  update: (id: string, data: WebhookUpdate) => client.patch<Webhook>(`/webhooks/${id}`, data),

  delete: (id: string) => client.delete(`/webhooks/${id}`),

  test: (id: string) => client.post<WebhookDelivery>(`/webhooks/${id}/test`),

  deliveries: (id: string) => client.get<WebhookDelivery[]>(`/webhooks/${id}/deliveries`),
};

export const operatingExpenses = {
  list: (params?: { lease_id?: string; year?: number; category?: string }) =>
    client.get<OperatingExpense[]>('/operating-expenses', { params }),

  create: (data: OperatingExpenseCreate) =>
    client.post<OperatingExpense>('/operating-expenses', data),

  update: (id: string, data: OperatingExpenseUpdate) =>
    client.patch<OperatingExpense>(`/operating-expenses/${id}`, data),

  delete: (id: string) => client.delete(`/operating-expenses/${id}`),

  variance: (params?: { lease_id?: string; year?: number }) =>
    client.get<OperatingExpenseVariance[]>('/operating-expenses/variance', { params }),
};

export const buildium = {
  getConnection: () => client.get<BuildiumConnection>('/buildium/connection'),

  saveConnection: (data: BuildiumConnectionInput) =>
    client.put<BuildiumConnection>('/buildium/connection', data),

  testConnection: () => client.post<BuildiumTestConnectionResult>('/buildium/connection/test'),

  listEntityTypes: () => client.get<BuildiumEntityType[]>('/buildium/entities'),

  listGlMapping: () => client.get<BuildiumGLAccountMapping[]>('/buildium/gl-mapping'),

  updateGlMapping: (id: string, gl_account_id: string) =>
    client.put<BuildiumGLAccountMapping>(`/buildium/gl-mapping/${id}`, { gl_account_id }),

  startMigration: (data: BuildiumMigrateRequest) =>
    client.post<BuildiumMigrationRun>('/buildium/migrate', data),

  listRuns: () => client.get<BuildiumMigrationRun[]>('/buildium/runs'),

  getRun: (id: string) => client.get<BuildiumMigrationRun>(`/buildium/runs/${id}`),

  cancelRun: (id: string) => client.post<BuildiumMigrationRun>(`/buildium/runs/${id}/cancel`),

  getSummary: () => client.get<Record<string, number>>('/buildium/summary'),
};

export const organizations = {
  signup: (data: SignupRequest) =>
    client.post<SignupResponse>('/organizations/signup', data),

  getMe: () => client.get<Organization>('/organizations/me'),

  get: (id: string) => client.get<Organization>(`/organizations/${id}`),

  list: () => client.get<Organization[]>('/organizations'),

  create: (data: OrganizationCreate) => client.post<Organization>('/organizations', data),

  update: (id: string, data: OrganizationUpdate) =>
    client.patch<Organization>(`/organizations/${id}`, data),
};

// ─── Vendor Portal (internal: admin generates token) ─────────────────────────
export const vendorPortalInternal = {
  generateToken: (vendorId: string) =>
    client.post<PortalTokenResponse>(`/vendors/${vendorId}/portal-token`),

  assignVendor: (ticketId: string, vendorId: string | null) =>
    client.patch(`/maintenance-tickets/${ticketId}/vendor`, { vendor_id: vendorId }),
};

// ─── Vendor Portal (external: vendor-facing, uses X-Vendor-Token header) ─────
import axios from 'axios';

const _portalBase = import.meta.env.VITE_API_BASE_URL || '/api/v1';

const _portalClient = (token: string) =>
  axios.create({
    baseURL: _portalBase,
    headers: { 'Content-Type': 'application/json', 'X-Vendor-Token': token },
  });

export const vendorPortal = {
  getProfile: (token: string) =>
    _portalClient(token).get<VendorPortalProfile>('/vendor-portal/me'),

  updateProfile: (token: string, data: Partial<VendorPortalProfile>) =>
    _portalClient(token).patch<VendorPortalProfile>('/vendor-portal/me', data),

  listTickets: (token: string) =>
    _portalClient(token).get<PortalTicket[]>('/vendor-portal/tickets'),

  getTicket: (token: string, id: string) =>
    _portalClient(token).get<PortalTicket>(`/vendor-portal/tickets/${id}`),

  updateTicket: (token: string, id: string, data: PortalTicketUpdate) =>
    _portalClient(token).patch<PortalTicket>(`/vendor-portal/tickets/${id}`, data),

  completeTicket: (token: string, id: string, notes: string) =>
    _portalClient(token).post<PortalTicket>(`/vendor-portal/tickets/${id}/complete`, { notes }),

  listContacts: (token: string) =>
    _portalClient(token).get<EntityContact[]>('/vendor-portal/contacts'),

  createContact: (token: string, data: EntityContactCreate) =>
    _portalClient(token).post<EntityContact>('/vendor-portal/contacts', data),

  updateContact: (token: string, id: string, data: EntityContactUpdate) =>
    _portalClient(token).put<EntityContact>(`/vendor-portal/contacts/${id}`, data),

  deleteContact: (token: string, id: string) =>
    _portalClient(token).delete(`/vendor-portal/contacts/${id}`),

  listInsurance: (token: string) =>
    _portalClient(token).get<VendorPortalCOI[]>('/vendor-portal/insurance'),

  reuploadInsurance: (token: string, formData: FormData) =>
    _portalClient(token).post<VendorPortalCOI>('/vendor-portal/insurance/reupload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
};

// ─── Client Portal (internal: admin generates one-time signup invite) ────────
export const clientPortalInternal = {
  generateInvite: (entityType: ClientPortalEntityType, entityId: string) =>
    client.post<ClientPortalInviteResponse>('/client-portal/invite', {
      entity_type: entityType,
      entity_id: entityId,
    }),

  status: (entityType: ClientPortalEntityType, entityId: string) =>
    client.get<ClientPortalStatus>('/client-portal/admin/status', {
      params: { entity_type: entityType, entity_id: entityId },
    }),

  revoke: (entityType: ClientPortalEntityType, entityId: string) =>
    client.post<ClientPortalStatus>('/client-portal/admin/revoke', {
      entity_type: entityType,
      entity_id: entityId,
    }),

  rotate: (entityType: ClientPortalEntityType, entityId: string) =>
    client.post<ClientPortalSession>('/client-portal/admin/rotate', {
      entity_type: entityType,
      entity_id: entityId,
    }),

  listChangeRequests: (
    entityType: ClientPortalEntityType,
    entityId: string,
    statusFilter?: ClientPortalChangeRequestStatus,
  ) =>
    client.get<ClientPortalChangeRequest[]>('/client-portal/admin/change-requests', {
      params: { entity_type: entityType, entity_id: entityId, status_filter: statusFilter },
    }),

  approveChangeRequest: (id: string, reviewNote?: string) =>
    client.post<ClientPortalChangeRequest>(
      `/client-portal/admin/change-requests/${id}/approve`,
      { review_note: reviewNote },
    ),

  rejectChangeRequest: (id: string, reviewNote?: string) =>
    client.post<ClientPortalChangeRequest>(
      `/client-portal/admin/change-requests/${id}/reject`,
      { review_note: reviewNote },
    ),
};

// ─── Client Portal (external: landlord/management-company self-service) ───────
const _clientPortalClient = (token: string) =>
  axios.create({
    baseURL: _portalBase,
    headers: { 'Content-Type': 'application/json', 'X-Portal-Token': token },
  });

export const clientPortal = {
  signup: (token: string) =>
    axios
      .create({ baseURL: _portalBase, headers: { 'Content-Type': 'application/json' } })
      .post<ClientPortalSession>('/client-portal/signup', { token }),

  getProfile: (token: string) =>
    _clientPortalClient(token).get<ClientPortalProfile>('/client-portal/me'),

  listContacts: (token: string) =>
    _clientPortalClient(token).get<EntityContact[]>('/client-portal/contacts'),

  createContact: (token: string, data: EntityContactCreate) =>
    _clientPortalClient(token).post<EntityContact>('/client-portal/contacts', data),

  updateContact: (token: string, id: string, data: EntityContactUpdate) =>
    _clientPortalClient(token).put<EntityContact>(`/client-portal/contacts/${id}`, data),

  deleteContact: (token: string, id: string) =>
    _clientPortalClient(token).delete(`/client-portal/contacts/${id}`),

  listDocuments: (token: string) =>
    _clientPortalClient(token).get<Attachment[]>('/client-portal/documents'),

  uploadDocument: (token: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return axios.create({
      baseURL: _portalBase,
      headers: { 'X-Portal-Token': token },
    }).post<Attachment>('/client-portal/documents', form);
  },

  downloadDocument: (token: string, id: string) =>
    axios
      .create({ baseURL: _portalBase, headers: { 'X-Portal-Token': token }, responseType: 'blob' })
      .get<Blob>(`/client-portal/documents/${id}/download`),

  deleteDocument: (token: string, id: string) =>
    _clientPortalClient(token).delete(`/client-portal/documents/${id}`),

  listChangeRequests: (token: string) =>
    _clientPortalClient(token).get<ClientPortalChangeRequest[]>('/client-portal/change-requests'),

  createChangeRequest: (token: string, data: ClientPortalChangeRequestCreate) =>
    _clientPortalClient(token).post<ClientPortalChangeRequest>(
      '/client-portal/change-requests',
      data,
    ),

  summary: (token: string) =>
    _clientPortalClient(token).get<ClientPortalSummary>('/client-portal/summary'),

  listOffices: (token: string) =>
    _clientPortalClient(token).get<ClientPortalOffice[]>('/client-portal/offices'),

  listLeases: (token: string) =>
    _clientPortalClient(token).get<ClientPortalLease[]>('/client-portal/leases'),

  listMaintenance: (token: string) =>
    _clientPortalClient(token).get<ClientPortalTicket[]>('/client-portal/maintenance'),
};

// ─── Resident Portal (external: resident self-service, X-Resident-Token) ──────
const _residentPortalClient = (token: string) =>
  axios.create({
    baseURL: _portalBase,
    headers: { 'Content-Type': 'application/json', 'X-Resident-Token': token },
  });

export const residentPortal = {
  signup: (token: string) =>
    axios
      .create({ baseURL: _portalBase, headers: { 'Content-Type': 'application/json' } })
      .post<PortalSession>('/resident-portal/signup', { token }),

  getProfile: (token: string) =>
    _residentPortalClient(token).get<ResidentPortalProfile>('/resident-portal/me'),

  listLeases: (token: string) =>
    _residentPortalClient(token).get<ResidentPortalLease[]>('/resident-portal/leases'),

  getBalance: (token: string) =>
    _residentPortalClient(token).get<ResidentPortalBalance>('/resident-portal/balance'),

  listMaintenanceRequests: (token: string) =>
    _residentPortalClient(token).get<ResidentPortalTicket[]>('/resident-portal/maintenance-requests'),

  createMaintenanceRequest: (token: string, data: ResidentPortalMaintenanceCreate) =>
    _residentPortalClient(token).post<ResidentPortalTicket>(
      '/resident-portal/maintenance-requests',
      data,
    ),

  listDocuments: (token: string) =>
    _residentPortalClient(token).get<Attachment[]>('/resident-portal/documents'),

  listAnnouncements: (token: string) =>
    _residentPortalClient(token).get<ResidentPortalAnnouncement[]>('/resident-portal/announcements'),
};

// ─── Owner Portal (external: property-owner self-service, X-Owner-Token) ──────
const _ownerPortalClient = (token: string) =>
  axios.create({
    baseURL: _portalBase,
    headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
  });

export const ownerPortal = {
  signup: (token: string) =>
    axios
      .create({ baseURL: _portalBase, headers: { 'Content-Type': 'application/json' } })
      .post<PortalSession>('/owner-portal/signup', { token }),

  getProfile: (token: string) =>
    _ownerPortalClient(token).get<OwnerPortalProfile>('/owner-portal/me'),

  listProperties: (token: string) =>
    _ownerPortalClient(token).get<OwnerPortalProperty[]>('/owner-portal/properties'),

  listLedger: (token: string) =>
    _ownerPortalClient(token).get<OwnerPortalLedgerEntry[]>('/owner-portal/ledger'),

  getBalance: (token: string) =>
    _ownerPortalClient(token).get<OwnerPortalBalance>('/owner-portal/balance'),

  getStatement: (token: string, startDate?: string, endDate?: string) =>
    _ownerPortalClient(token).get<OwnerPortalStatement>('/owner-portal/statement', {
      params: { start_date: startDate || undefined, end_date: endDate || undefined },
    }),

  listDistributions: (token: string) =>
    _ownerPortalClient(token).get<OwnerPortalDistribution[]>('/owner-portal/distributions'),
};

// ─── Insurance Certificates ───────────────────────────────────────────────────
export const insuranceCertificates = {
  list: (params?: { vendor_id?: string; landlord_id?: string; expired_only?: boolean; expiring_within_days?: number }) =>
    client.get<InsuranceCertificate[]>('/insurance-certificates', { params }),

  compliance: () =>
    client.get<InsuranceCertComplianceSummary>('/insurance-certificates/compliance'),

  get: (id: string) =>
    client.get<InsuranceCertificate>(`/insurance-certificates/${id}`),

  create: (data: InsuranceCertificateCreate) =>
    client.post<InsuranceCertificate>('/insurance-certificates', data),

  update: (id: string, data: InsuranceCertificateUpdate) =>
    client.patch<InsuranceCertificate>(`/insurance-certificates/${id}`, data),

  delete: (id: string) =>
    client.delete(`/insurance-certificates/${id}`),
};

// ─── Maintenance program ──────────────────────────────────────────────────────
export const maintenance = {
  catalog: () => client.get<MaintenanceCatalog>('/maintenance/catalog'),

  updateCategorySubtopics: (category: string, data: { subtopics: MaintenanceCatalogSubtopic[] }) =>
    client.put<MaintenanceCatalogCategory>(`/maintenance/categories/${category}/subtopics`, data),

  resetCategorySubtopics: (category: string) =>
    client.delete<MaintenanceCatalogCategory>(`/maintenance/categories/${category}/subtopics`),

  overview: () => client.get<MaintenanceOverview>('/maintenance/overview'),

  compliance: () => client.get<MaintenanceCompliance>('/maintenance/compliance'),

  listAssets: (params?: { category?: string; office_id?: string }) =>
    client.get<MaintenanceAsset[]>('/maintenance/assets', { params }),

  createAsset: (data: Partial<MaintenanceAsset>) =>
    client.post<MaintenanceAsset>('/maintenance/assets', data),

  updateAsset: (id: string, data: Partial<MaintenanceAsset>) =>
    client.patch<MaintenanceAsset>(`/maintenance/assets/${id}`, data),

  deleteAsset: (id: string) => client.delete(`/maintenance/assets/${id}`),

  listTasks: (params?: {
    category?: string;
    office_id?: string;
    vendor_id?: string;
    asset_id?: string;
    due_within_days?: number;
    overdue_only?: boolean;
  }) => client.get<MaintenanceTask[]>('/maintenance/tasks', { params }),

  createTask: (data: Partial<MaintenanceTask>) =>
    client.post<MaintenanceTask>('/maintenance/tasks', data),

  updateTask: (id: string, data: Partial<MaintenanceTask>) =>
    client.patch<MaintenanceTask>(`/maintenance/tasks/${id}`, data),

  deleteTask: (id: string) => client.delete(`/maintenance/tasks/${id}`),

  generateWorkOrder: (id: string) =>
    client.post<GenerateWorkOrderResult>(`/maintenance/tasks/${id}/generate-work-order`),

  listLogs: (params?: { task_id?: string; asset_id?: string }) =>
    client.get<MaintenanceLog[]>('/maintenance/logs', { params }),

  createLog: (data: Partial<MaintenanceLog>) =>
    client.post<MaintenanceLog>('/maintenance/logs', data),

  deleteLog: (id: string) => client.delete(`/maintenance/logs/${id}`),
};

// ─── General Ledger ──────────────────────────────────────────────────────────
export const gl = {
  listAccounts: () => client.get<GLAccount[]>('/gl/accounts'),

  createAccount: (data: GLAccountCreate) =>
    client.post<GLAccount>('/gl/accounts', data),

  updateAccount: (id: string, data: Partial<GLAccountCreate> & { is_active?: boolean }) =>
    client.patch<GLAccount>(`/gl/accounts/${id}`, data),

  listPeriods: () => client.get<AccountingPeriod[]>('/gl/periods'),

  closePeriod: (year: number, month: number) =>
    client.post<AccountingPeriod>(`/gl/periods/${year}/${month}/close`),

  reopenPeriod: (year: number, month: number) =>
    client.post<AccountingPeriod>(`/gl/periods/${year}/${month}/reopen`),

  listEntries: (params?: { source?: string; year?: number; month?: number }) =>
    client.get<JournalEntry[]>('/gl/journal-entries', { params }),

  createEntry: (data: JournalEntryCreate) =>
    client.post<JournalEntry>('/gl/journal-entries', data),

  postLease: (leaseId: string) =>
    client.post<JournalEntry[]>(`/gl/journal-entries/post-lease/${leaseId}`),

  trialBalance: (params?: { year?: number; month?: number }) =>
    client.get<TrialBalanceRow[]>('/gl/trial-balance', { params }),

  exportCsv: (params?: { year?: number; month?: number }) =>
    client.get('/gl/export', { params, responseType: 'blob' }),
};

// ─── CAM Reconciliation ──────────────────────────────────────────────────────
export const cam = {
  list: (params?: { lease_id?: string; year?: number }) =>
    client.get<CamReconciliation[]>('/cam/reconciliations', { params }),

  get: (id: string) =>
    client.get<CamReconciliation>(`/cam/reconciliations/${id}`),

  create: (data: CamReconciliationCreate) =>
    client.post<CamReconciliation>('/cam/reconciliations', data),

  update: (id: string, data: CamReconciliationUpdate) =>
    client.patch<CamReconciliation>(`/cam/reconciliations/${id}`, data),

  delete: (id: string) => client.delete(`/cam/reconciliations/${id}`),

  finalize: (id: string) =>
    client.post<CamReconciliation>(`/cam/reconciliations/${id}/finalize`),

  postToGl: (id: string) =>
    client.post(`/cam/reconciliations/${id}/post-to-gl`),

  aiReview: (id: string) =>
    client.post<CamReviewResponse>(`/cam/reconciliations/${id}/ai-review`),
};

// ─── Accounts Payable ────────────────────────────────────────────────────────
export const ap = {
  listBills: (params?: { vendor_id?: string; status?: string }) =>
    client.get<VendorBill[]>('/ap/bills', { params }),

  getBill: (id: string) => client.get<VendorBill>(`/ap/bills/${id}`),

  createBill: (data: BillCreate) => client.post<VendorBill>('/ap/bills', data),

  updateBill: (id: string, data: BillUpdate) =>
    client.patch<VendorBill>(`/ap/bills/${id}`, data),

  deleteBill: (id: string) => client.delete(`/ap/bills/${id}`),

  finalizeBill: (id: string) =>
    client.post<VendorBill>(`/ap/bills/${id}/finalize`),

  voidBill: (id: string) => client.post<VendorBill>(`/ap/bills/${id}/void`),

  createPayment: (billId: string, data: PaymentCreate) =>
    client.post<VendorBill>(`/ap/bills/${billId}/payments`, data),

  deletePayment: (paymentId: string) =>
    client.delete<VendorBill>(`/ap/payments/${paymentId}`),
};

// ─── Accounts Receivable ─────────────────────────────────────────────────────
export const ar = {
  listCustomers: (params?: { q?: string }) =>
    client.get<Customer[]>('/ar/customers', { params }),

  createCustomer: (data: CustomerCreate) =>
    client.post<Customer>('/ar/customers', data),

  updateCustomer: (id: string, data: CustomerUpdate) =>
    client.patch<Customer>(`/ar/customers/${id}`, data),

  deleteCustomer: (id: string) => client.delete(`/ar/customers/${id}`),

  listInvoices: (params?: { customer_id?: string; status?: string; open_only?: boolean }) =>
    client.get<CustomerInvoice[]>('/ar/invoices', { params }),

  getInvoice: (id: string) => client.get<CustomerInvoice>(`/ar/invoices/${id}`),

  createInvoice: (data: InvoiceCreate) =>
    client.post<CustomerInvoice>('/ar/invoices', data),

  updateInvoice: (id: string, data: InvoiceUpdate) =>
    client.patch<CustomerInvoice>(`/ar/invoices/${id}`, data),

  deleteInvoice: (id: string) => client.delete(`/ar/invoices/${id}`),

  finalizeInvoice: (id: string) =>
    client.post<CustomerInvoice>(`/ar/invoices/${id}/finalize`),

  voidInvoice: (id: string) => client.post<CustomerInvoice>(`/ar/invoices/${id}/void`),

  createReceipt: (invoiceId: string, data: ReceiptCreate) =>
    client.post<CustomerInvoice>(`/ar/invoices/${invoiceId}/receipts`, data),

  deleteReceipt: (receiptId: string) =>
    client.delete<CustomerInvoice>(`/ar/receipts/${receiptId}`),

  invoiceFromCam: (
    reconciliationId: string,
    params: { customer_id: string; invoice_date?: string; due_date?: string },
  ) =>
    client.post<CustomerInvoice>(`/ar/invoices/from-cam/${reconciliationId}`, null, { params }),

  aging: (params?: { as_of?: string }) =>
    client.get<ArAgingReport>('/ar/aging', { params }),
};

// ─── Bank Reconciliation ─────────────────────────────────────────────────────
export const bank = {
  listAccounts: (params?: { active_only?: boolean }) =>
    client.get<BankAccount[]>('/bank/accounts', { params }),

  getAccount: (id: string) => client.get<BankAccount>(`/bank/accounts/${id}`),

  createAccount: (data: BankAccountCreate) =>
    client.post<BankAccount>('/bank/accounts', data),

  updateAccount: (id: string, data: BankAccountUpdate) =>
    client.patch<BankAccount>(`/bank/accounts/${id}`, data),

  deleteAccount: (id: string) => client.delete(`/bank/accounts/${id}`),

  listTransactions: (
    accountId: string,
    params?: { status?: string; unreconciled_only?: boolean },
  ) => client.get<BankTransaction[]>(`/bank/accounts/${accountId}/transactions`, { params }),

  createTransaction: (accountId: string, data: BankTransactionCreate) =>
    client.post<BankTransaction>(`/bank/accounts/${accountId}/transactions`, data),

  importStatement: (accountId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post<BankImportResult>(
      `/bank/accounts/${accountId}/import`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
  },

  deleteTransaction: (transactionId: string) =>
    client.delete(`/bank/transactions/${transactionId}`),

  listReconciliations: (accountId: string) =>
    client.get<BankReconciliation[]>(`/bank/accounts/${accountId}/reconciliations`),

  createReconciliation: (accountId: string, data: BankReconciliationCreate) =>
    client.post<BankReconciliation>(`/bank/accounts/${accountId}/reconciliations`, data),

  getReconciliationReport: (reconciliationId: string) =>
    client.get<ReconciliationReport>(`/bank/reconciliations/${reconciliationId}`),

  clear: (reconciliationId: string, transactionIds: string[]) =>
    client.post<BankReconciliation>(`/bank/reconciliations/${reconciliationId}/clear`, {
      transaction_ids: transactionIds,
    }),

  unclear: (reconciliationId: string, transactionIds: string[]) =>
    client.post<BankReconciliation>(`/bank/reconciliations/${reconciliationId}/unclear`, {
      transaction_ids: transactionIds,
    }),

  complete: (reconciliationId: string) =>
    client.post<BankReconciliation>(`/bank/reconciliations/${reconciliationId}/complete`),

  reopen: (reconciliationId: string) =>
    client.post<BankReconciliation>(`/bank/reconciliations/${reconciliationId}/reopen`),

  deleteReconciliation: (reconciliationId: string) =>
    client.delete(`/bank/reconciliations/${reconciliationId}`),
};


// ─── Tax / 1099 (Phase 1.3) ──────────────────────────────────────────────────
export const tax = {
  list1099: (params: { year: number; form?: string; only_reportable?: boolean }) =>
    client.get<Vendor1099Summary[]>('/tax/1099', { params }),

  get1099Detail: (vendorId: string, year: number) =>
    client.get<Vendor1099Detail>(`/tax/1099/${vendorId}`, { params: { year } }),

  export1099: (params: { year: number; form?: string; only_reportable?: boolean }) =>
    client.get('/tax/1099/export', { params, responseType: 'blob' }),
};


// ─── Budgeting (Phase 1.4) ───────────────────────────────────────────────────
export const budgets = {
  list: (params?: { fiscal_year?: number }) =>
    client.get<Budget[]>('/budgets', { params }),

  get: (id: string) => client.get<Budget>(`/budgets/${id}`),

  create: (data: BudgetCreate) => client.post<Budget>('/budgets', data),

  update: (id: string, data: BudgetUpdate) =>
    client.patch<Budget>(`/budgets/${id}`, data),

  remove: (id: string) => client.delete(`/budgets/${id}`),

  report: (id: string, params?: { as_of?: string }) =>
    client.get<BudgetReport>(`/budgets/${id}/report`, { params }),
};


// ─── Property Inspections (Phase 1.5) ────────────────────────────────────────
export const inspections = {
  listTemplates: (params?: { active_only?: boolean }) =>
    client.get<InspectionTemplate[]>('/inspections/templates', { params }),

  getTemplate: (id: string) =>
    client.get<InspectionTemplate>(`/inspections/templates/${id}`),

  createTemplate: (data: InspectionTemplateCreate) =>
    client.post<InspectionTemplate>('/inspections/templates', data),

  updateTemplate: (id: string, data: InspectionTemplateUpdate) =>
    client.patch<InspectionTemplate>(`/inspections/templates/${id}`, data),

  removeTemplate: (id: string) => client.delete(`/inspections/templates/${id}`),

  list: (params?: { office_id?: string; status?: string }) =>
    client.get<Inspection[]>('/inspections', { params }),

  get: (id: string) => client.get<Inspection>(`/inspections/${id}`),

  create: (data: InspectionCreate) =>
    client.post<Inspection>('/inspections', data),

  update: (id: string, data: InspectionUpdate) =>
    client.patch<Inspection>(`/inspections/${id}`, data),

  complete: (id: string) =>
    client.post<Inspection>(`/inspections/${id}/complete`),

  remove: (id: string) => client.delete(`/inspections/${id}`),
};




// ─── Lease Lifecycle Accounting ──────────────────────────────────────────────
export const lifecycle = {
  list: (params?: { lease_id?: string; event_type?: string }) =>
    client.get<LifecycleEvent[]>('/lifecycle/events', { params }),

  get: (id: string) => client.get<LifecycleEvent>(`/lifecycle/events/${id}`),

  create: (data: LifecycleEventCreate) =>
    client.post<LifecycleEvent>('/lifecycle/events', data),

  update: (id: string, data: LifecycleEventUpdate) =>
    client.patch<LifecycleEvent>(`/lifecycle/events/${id}`, data),

  delete: (id: string) => client.delete(`/lifecycle/events/${id}`),

  finalize: (id: string) =>
    client.post<LifecycleEvent>(`/lifecycle/events/${id}/finalize`),

  postToGl: (id: string) =>
    client.post(`/lifecycle/events/${id}/post-to-gl`),
};

// ─── Financial Statements ────────────────────────────────────────────────────
export const financials = {
  incomeStatement: (params?: { year?: number; month?: number }) =>
    client.get<IncomeStatementResponse>('/financials/income-statement', { params }),

  balanceSheet: (params?: { year?: number; month?: number }) =>
    client.get<BalanceSheetResponse>('/financials/balance-sheet', { params }),

  cashFlowStatement: (params?: { year?: number; month?: number }) =>
    client.get<CashFlowStatementResponse>('/financials/cash-flow-statement', { params }),

  auditReport: () =>
    client.get<AuditReportResponse>('/financials/audit-report'),
};

// ─── AI assist (Google Gemini) ───────────────────────────────────────────────
import type {
  AIStatus,
  LeaseParseResult,
  AbstractSuggestResult,
  DocumentClassifyResult,
  DocumentParseResult,
  AISummaryResult,
  TicketTriageResult,
  SimilarTicketsResult,
  AssistantQueryResult,
  AssistantReindexResult,
  LeaseDocumentSearchResult,
  LeaseIndexedDocumentsResult,
  LeaseDocumentTextResult,
  PortfolioAskResult,
  WaiverTemplateCreate,
  WaiverTemplateUpdate,
  WaiverRequestItem,
  SendWaiverRequest as SendWaiverRequestType,
  WaiverRecipientSuggestion,
  WaiverDuplicateCheck,
  PublicWaiverView,
  WaiverSignSubmission,
} from '@/types';

export const ai = {
  status: () => client.get<AIStatus>('/ai/status'),

  parseLease: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client.post<LeaseParseResult>('/ai/leases/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  suggestAbstract: (leaseId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client.post<AbstractSuggestResult>(`/ai/leases/${leaseId}/abstract/suggest`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  classifyDocument: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client.post<DocumentClassifyResult>('/ai/documents/classify', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  parseVendorBill: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client.post<DocumentParseResult>('/ai/ap/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  parseInsuranceCertificate: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client.post<DocumentParseResult>('/ai/insurance/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  parseHvacContract: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client.post<DocumentParseResult>('/ai/hvac-contracts/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  parseLeaseTemplate: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return client.post<LeaseTemplateDraftResult>('/ai/lease-templates/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  summary: (period: 'weekly' | 'monthly') =>
    client.post<AISummaryResult>('/ai/reports/summary', { period }),

  triageTicket: (subject: string, description: string) =>
    client.post<TicketTriageResult>('/ai/tickets/triage', { subject, description }),

  similarTickets: (
    subject: string,
    description: string,
    excludeId?: string | null,
    limit = 5,
  ) =>
    client.post<SimilarTicketsResult>('/ai/tickets/similar', {
      subject,
      description,
      exclude_id: excludeId ?? null,
      limit,
    }),

  draftTicketFromEmail: (emailText: string) =>
    client.post<DocumentParseResult>('/ai/tickets/draft-from-email', { email_text: emailText }),

  assistantQuery: (question: string, limit = 12) =>
    client.post<AssistantQueryResult>('/ai/assistant/query', { question, limit }),

  assistantReindex: () =>
    client.post<AssistantReindexResult>('/ai/assistant/reindex', {}),

  exportSummary: (narrative: string, periodLabel: string, format: 'pdf' | 'docx') =>
    client.post<Blob>(
      '/ai/reports/summary/export',
      { narrative, period_label: periodLabel, format },
      { responseType: 'blob' },
    ),

  searchLeaseDocuments: (
    leaseId: string,
    query: string,
    limit = 10,
    attachmentId?: string | null,
  ) =>
    client.post<LeaseDocumentSearchResult>(`/leases/${leaseId}/document-search`, {
      query,
      limit,
      attachment_id: attachmentId ?? null,
    }),

  listLeaseDocuments: (leaseId: string) =>
    client.get<LeaseIndexedDocumentsResult>(`/leases/${leaseId}/documents`),

  searchAllLeaseDocuments: (query: string, limit = 10) =>
    client.post<LeaseDocumentSearchResult>('/leases/document-search', { query, limit }),

  getLeaseDocumentText: (leaseId: string, attachmentId: string) =>
    client.get<LeaseDocumentTextResult>(
      `/leases/${leaseId}/documents/${attachmentId}/text`,
    ),

  reindexLeaseDocuments: (leaseId: string) =>
    client.post<{ lease_id: string; chunks_indexed: number }>(
      `/leases/${leaseId}/reindex-documents`,
    ),

  askPortfolio: (question: string, limit = 8) =>
    client.post<PortfolioAskResult>('/ai/portfolio/ask', { question, limit }),
};

// ─── Digital Waivers (internal, gated) ───────────────────────────────────────
export const waivers = {
  listTemplates: () => client.get<WaiverTemplateType[]>('/waivers/templates'),

  createTemplate: (data: WaiverTemplateCreate) =>
    client.post<WaiverTemplateType>('/waivers/templates', data),

  updateTemplate: (id: string, data: WaiverTemplateUpdate) =>
    client.put<WaiverTemplateType>(`/waivers/templates/${id}`, data),

  deleteTemplate: (id: string) => client.delete(`/waivers/templates/${id}`),

  send: (data: SendWaiverRequestType) =>
    client.post<WaiverRequestItem>('/waivers/send', data),

  searchRecipients: (q: string, limit = 10) =>
    client.get<WaiverRecipientSuggestion[]>('/waivers/recipients/search', {
      params: { q, limit },
    }),

  checkDuplicate: (recipient_email: string, template_id?: string | null) =>
    client.post<WaiverDuplicateCheck>('/waivers/recipients/duplicate-check', {
      recipient_email,
      template_id: template_id ?? null,
    }),

  listRequests: (params?: { q?: string; status?: string }) =>
    client.get<WaiverRequestItem[]>('/waivers/requests', { params }),

  deleteRequest: (id: string) => client.delete(`/waivers/requests/${id}`),

  downloadPdf: (id: string) =>
    client.get(`/waivers/requests/${id}/pdf`, { responseType: 'blob' }),
};

// ─── Digital Waivers (public, token-based signing) ───────────────────────────
const _waiverBase = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export const waiverPublic = {
  view: (token: string) =>
    axios.create({ baseURL: _waiverBase }).get<PublicWaiverView>(`/waivers/sign/${token}`),

  sign: (token: string, data: WaiverSignSubmission) =>
    axios.create({ baseURL: _waiverBase }).post<PublicWaiverView>(`/waivers/sign/${token}`, data),

  decline: (token: string) =>
    axios.create({ baseURL: _waiverBase }).post<PublicWaiverView>(`/waivers/decline/${token}`),
};

// ─── Email reminders (public, token-based acknowledgement) ───────────────────
export interface EmailAckView {
  subject: string;
  rule_name: string | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
}

export const emailAckPublic = {
  view: (token: string) =>
    axios.create({ baseURL: _waiverBase }).get<EmailAckView>(`/email-rules/ack/${token}`),

  confirm: (token: string) =>
    axios.create({ baseURL: _waiverBase }).post<EmailAckView>(`/email-rules/ack/${token}`),
};

// ─── Residential / Buildium-parity domains ───────────────────────────────────
import type {
  RentalUnit,
  RentalUnitCreate,
  RentalUnitUpdate,
  Resident,
  ResidentCreate,
  ResidentUpdate,
  ResidentLease,
  ResidentLeaseCreate,
  ResidentLeaseUpdate,
  OccupancySummary,
  RentCharge,
  RentChargeCreate,
  RentChargeUpdate,
  SecurityDeposit,
  DepositCreate,
  DepositReturn,
  RentPaymentCreate,
  RentPaymentResult,
  BillingRunResult,
  LateFeeRunResult,
  RentalApplication,
  RentalApplicationCreate,
  RentalApplicationUpdate,
  ScreeningReport,
  LeaseSignatureRequest,
  LeaseSignatureCreate,
  LeaseSignatureFromTemplate,
  LeaseTemplate,
  LeaseTemplateCreate,
  LeaseTemplateUpdate,
  LeaseTemplateSample,
  PublicLeaseView,
  LeaseSignSubmission,
  ApplicationTemplate,
  ApplicationTemplateCreate,
  ApplicationTemplateUpdate,
  ApplicationTemplateSample,
  ApplicationFromTemplate,
  PublicApplicationView,
  ApplicationSignSubmission,
  VacancyListing,
  VacancyListingCreate,
  VacancyListingUpdate,
  ListingPortal,
  ListingPortalCreate,
  ListingPortalUpdate,
  KnownPortal,
  ListingSyndication,
  LeaseTemplateDraftResult,
  Announcement,
  AnnouncementCreate,
  AnnouncementUpdate,
  AnnouncementSendResult,
  PropertyOwner,
  PropertyOwnerCreate,
  PropertyOwnerUpdate,
  OwnerProperty,
  OwnerPropertyCreate,
  OwnerLedgerEntry,
  OwnerLedgerEntryCreate,
  OwnerBalance,
  OwnerDistribution,
  OwnerDistributionCreate,
  OwnerStatement,
  TrustAccount,
  TrustAccountCreate,
  TrustAccountUpdate,
  PortalInviteResponse,
} from '@/types';

export const leasing = {
  occupancy: () => client.get<OccupancySummary>('/leasing/occupancy'),

  listUnits: (params?: { office_id?: string; status?: string; q?: string }) =>
    client.get<RentalUnit[]>('/leasing/units', { params }),
  getUnit: (id: string) => client.get<RentalUnit>(`/leasing/units/${id}`),
  createUnit: (data: RentalUnitCreate) => client.post<RentalUnit>('/leasing/units', data),
  updateUnit: (id: string, data: RentalUnitUpdate) =>
    client.patch<RentalUnit>(`/leasing/units/${id}`, data),
  deleteUnit: (id: string) => client.delete(`/leasing/units/${id}`),

  listResidents: (params?: { status?: string; q?: string }) =>
    client.get<Resident[]>('/leasing/residents', { params }),
  getResident: (id: string) => client.get<Resident>(`/leasing/residents/${id}`),
  createResident: (data: ResidentCreate) => client.post<Resident>('/leasing/residents', data),
  updateResident: (id: string, data: ResidentUpdate) =>
    client.patch<Resident>(`/leasing/residents/${id}`, data),
  deleteResident: (id: string) => client.delete(`/leasing/residents/${id}`),

  inviteToPortal: (id: string) =>
    client.post<PortalInviteResponse>('/resident-portal/invite', { resident_id: id }),

  listLeases: (params?: { unit_id?: string; resident_id?: string; status?: string }) =>
    client.get<ResidentLease[]>('/leasing/leases', { params }),
  getLease: (id: string) => client.get<ResidentLease>(`/leasing/leases/${id}`),
  createLease: (data: ResidentLeaseCreate) =>
    client.post<ResidentLease>('/leasing/leases', data),
  updateLease: (id: string, data: ResidentLeaseUpdate) =>
    client.patch<ResidentLease>(`/leasing/leases/${id}`, data),
  deleteLease: (id: string) => client.delete(`/leasing/leases/${id}`),
};

export const rent = {
  listCharges: (params?: { resident_lease_id?: string; active?: boolean }) =>
    client.get<RentCharge[]>('/rent/charges', { params }),
  createCharge: (data: RentChargeCreate) => client.post<RentCharge>('/rent/charges', data),
  updateCharge: (id: string, data: RentChargeUpdate) =>
    client.patch<RentCharge>(`/rent/charges/${id}`, data),
  deleteCharge: (id: string) => client.delete(`/rent/charges/${id}`),
  generateInvoice: (chargeId: string, periodStart: string) =>
    client.post<BillingRunResult>(
      `/rent/charges/${chargeId}/generate-invoice`,
      undefined,
      { params: { period_start: periodStart } },
    ),
  runBilling: (asOf?: string) =>
    client.post<BillingRunResult>('/rent/run-billing', undefined, {
      params: asOf ? { as_of: asOf } : undefined,
    }),
  applyLateFees: (asOf?: string) =>
    client.post<LateFeeRunResult>('/rent/apply-late-fees', undefined, {
      params: asOf ? { as_of: asOf } : undefined,
    }),
  recordPayment: (data: RentPaymentCreate) =>
    client.post<RentPaymentResult>('/rent/payments', data),

  listDeposits: (params?: { resident_lease_id?: string }) =>
    client.get<SecurityDeposit[]>('/rent/deposits', { params }),
  createDeposit: (data: DepositCreate) => client.post<SecurityDeposit>('/rent/deposits', data),
  returnDeposit: (id: string, data: DepositReturn) =>
    client.post<SecurityDeposit>(`/rent/deposits/${id}/return`, data),
};

export const leasingFunnel = {
  listApplications: (params?: { status?: string; unit_id?: string }) =>
    client.get<RentalApplication[]>('/leasing-funnel/applications', { params }),
  getApplication: (id: string) =>
    client.get<RentalApplication>(`/leasing-funnel/applications/${id}`),
  createApplication: (data: RentalApplicationCreate) =>
    client.post<RentalApplication>('/leasing-funnel/applications', data),
  updateApplication: (id: string, data: RentalApplicationUpdate) =>
    client.patch<RentalApplication>(`/leasing-funnel/applications/${id}`, data),
  deleteApplication: (id: string) => client.delete(`/leasing-funnel/applications/${id}`),
  screen: (id: string) =>
    client.post<ScreeningReport>(`/leasing-funnel/applications/${id}/screen`),
  listScreening: (id: string) =>
    client.get<ScreeningReport[]>(`/leasing-funnel/applications/${id}/screening`),
  downloadSignedApplication: (id: string) =>
    client.get(`/leasing-funnel/applications/${id}/signed-pdf`, { responseType: 'blob' }),
  convert: (id: string) =>
    client.post<RentalApplication>(`/leasing-funnel/applications/${id}/convert`),
  createApplicationFromTemplate: (data: ApplicationFromTemplate) =>
    client.post<RentalApplication>('/leasing-funnel/applications/from-template', data),
  sendApplication: (id: string) =>
    client.post<RentalApplication>(`/leasing-funnel/applications/${id}/send`),

  listSignatures: (params?: { status?: string }) =>
    client.get<LeaseSignatureRequest[]>('/leasing-funnel/lease-signatures', { params }),
  getSignature: (id: string) =>
    client.get<LeaseSignatureRequest>(`/leasing-funnel/lease-signatures/${id}`),
  createSignature: (data: LeaseSignatureCreate) =>
    client.post<LeaseSignatureRequest>('/leasing-funnel/lease-signatures', data),
  createSignatureFromTemplate: (data: LeaseSignatureFromTemplate) =>
    client.post<LeaseSignatureRequest>('/leasing-funnel/lease-signatures/from-template', data),
  voidSignature: (id: string) =>
    client.post<LeaseSignatureRequest>(`/leasing-funnel/lease-signatures/${id}/void`),
  downloadSignedLease: (id: string) =>
    client.get(`/leasing-funnel/lease-signatures/${id}/pdf`, { responseType: 'blob' }),
};

export const leaseTemplates = {
  list: (params?: { active_only?: boolean }) =>
    client.get<LeaseTemplate[]>('/lease-templates', { params }),
  getSample: () => client.get<LeaseTemplateSample>('/lease-templates/sample'),
  get: (id: string) => client.get<LeaseTemplate>(`/lease-templates/${id}`),
  create: (data: LeaseTemplateCreate) => client.post<LeaseTemplate>('/lease-templates', data),
  update: (id: string, data: LeaseTemplateUpdate) =>
    client.patch<LeaseTemplate>(`/lease-templates/${id}`, data),
  delete: (id: string) => client.delete(`/lease-templates/${id}`),
};

export const applicationTemplates = {
  list: (params?: { active_only?: boolean }) =>
    client.get<ApplicationTemplate[]>('/application-templates', { params }),
  getSample: () => client.get<ApplicationTemplateSample>('/application-templates/sample'),
  get: (id: string) => client.get<ApplicationTemplate>(`/application-templates/${id}`),
  create: (data: ApplicationTemplateCreate) =>
    client.post<ApplicationTemplate>('/application-templates', data),
  update: (id: string, data: ApplicationTemplateUpdate) =>
    client.patch<ApplicationTemplate>(`/application-templates/${id}`, data),
  delete: (id: string) => client.delete(`/application-templates/${id}`),
};

// ─── Leasing funnel (public, token-based lease signing) ──────────────────────
const _leaseSignBase = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export const leasingFunnelPublic = {
  view: (token: string) =>
    axios
      .create({ baseURL: _leaseSignBase })
      .get<PublicLeaseView>(`/leasing-funnel/lease-sign/${token}`),

  sign: (token: string, data: LeaseSignSubmission) =>
    axios
      .create({ baseURL: _leaseSignBase })
      .post<PublicLeaseView>(`/leasing-funnel/lease-sign/${token}`, data),

  decline: (token: string) =>
    axios
      .create({ baseURL: _leaseSignBase })
      .post<PublicLeaseView>(`/leasing-funnel/lease-sign/${token}/decline`),

  // Staff-sent, template-based application: applicant fills + e-signs.
  viewApplication: (token: string) =>
    axios
      .create({ baseURL: _leaseSignBase })
      .get<PublicApplicationView>(`/leasing-funnel/apply/${token}`),

  submitApplication: (token: string, data: ApplicationSignSubmission) =>
    axios
      .create({ baseURL: _leaseSignBase })
      .post<PublicApplicationView>(`/leasing-funnel/apply/${token}`, data),
};

export const listings = {
  list: (params?: { status?: string; unit_id?: string }) =>
    client.get<VacancyListing[]>('/listings', { params }),
  get: (id: string) => client.get<VacancyListing>(`/listings/${id}`),
  create: (data: VacancyListingCreate) => client.post<VacancyListing>('/listings', data),
  update: (id: string, data: VacancyListingUpdate) =>
    client.patch<VacancyListing>(`/listings/${id}`, data),
  publish: (id: string) => client.post<VacancyListing>(`/listings/${id}/publish`),
  unpublish: (id: string) => client.post<VacancyListing>(`/listings/${id}/unpublish`),
  markLeased: (id: string) => client.post<VacancyListing>(`/listings/${id}/mark-leased`),
  remove: (id: string) => client.delete(`/listings/${id}`),

  // Portal syndication
  portalCatalog: () => client.get<KnownPortal[]>('/listings/portals/catalog'),
  listPortals: () => client.get<ListingPortal[]>('/listings/portals'),
  createPortal: (data: ListingPortalCreate) =>
    client.post<ListingPortal>('/listings/portals', data),
  updatePortal: (id: string, data: ListingPortalUpdate) =>
    client.patch<ListingPortal>(`/listings/portals/${id}`, data),
  removePortal: (id: string) => client.delete(`/listings/portals/${id}`),
  syndicate: (id: string, portalIds: string[]) =>
    client.post<ListingSyndication[]>(`/listings/${id}/syndicate`, { portal_ids: portalIds }),
  listSyndications: (id: string) =>
    client.get<ListingSyndication[]>(`/listings/${id}/syndications`),
};

export const announcements = {
  list: () => client.get<Announcement[]>('/announcements'),
  get: (id: string) => client.get<Announcement>(`/announcements/${id}`),
  create: (data: AnnouncementCreate) => client.post<Announcement>('/announcements', data),
  update: (id: string, data: AnnouncementUpdate) =>
    client.patch<Announcement>(`/announcements/${id}`, data),
  remove: (id: string) => client.delete(`/announcements/${id}`),
  send: (id: string) => client.post<AnnouncementSendResult>(`/announcements/${id}/send`),
};

export const owners = {
  list: (params?: { status?: string; q?: string }) =>
    client.get<PropertyOwner[]>('/owners/', { params }),
  get: (id: string) => client.get<PropertyOwner>(`/owners/${id}`),
  create: (data: PropertyOwnerCreate) => client.post<PropertyOwner>('/owners/', data),
  update: (id: string, data: PropertyOwnerUpdate) =>
    client.patch<PropertyOwner>(`/owners/${id}`, data),
  remove: (id: string) => client.delete(`/owners/${id}`),

  inviteToPortal: (id: string) =>
    client.post<PortalInviteResponse>('/owner-portal/invite', { owner_id: id }),

  listProperties: (ownerId: string) =>
    client.get<OwnerProperty[]>(`/owners/${ownerId}/properties`),
  addProperty: (ownerId: string, data: OwnerPropertyCreate) =>
    client.post<OwnerProperty>(`/owners/${ownerId}/properties`, data),
  removeProperty: (ownerId: string, propertyId: string) =>
    client.delete(`/owners/${ownerId}/properties/${propertyId}`),

  listLedger: (ownerId: string) =>
    client.get<OwnerLedgerEntry[]>(`/owners/${ownerId}/ledger`),
  addLedgerEntry: (ownerId: string, data: OwnerLedgerEntryCreate) =>
    client.post<OwnerLedgerEntry>(`/owners/${ownerId}/ledger`, data),
  balance: (ownerId: string) => client.get<OwnerBalance>(`/owners/${ownerId}/balance`),
  statement: (ownerId: string, params?: { start_date?: string; end_date?: string }) =>
    client.get<OwnerStatement>(`/owners/${ownerId}/statement`, { params }),

  listDistributions: (ownerId: string) =>
    client.get<OwnerDistribution[]>(`/owners/${ownerId}/distributions`),
  createDistribution: (ownerId: string, data: OwnerDistributionCreate) =>
    client.post<OwnerDistribution>(`/owners/${ownerId}/distributions`, data),
  markDistributionPaid: (ownerId: string, distributionId: string) =>
    client.post<OwnerDistribution>(
      `/owners/${ownerId}/distributions/${distributionId}/pay`,
    ),
  voidDistribution: (ownerId: string, distributionId: string) =>
    client.post<OwnerDistribution>(
      `/owners/${ownerId}/distributions/${distributionId}/void`,
    ),

  listTrustAccounts: () => client.get<TrustAccount[]>('/owners/trust-accounts'),
  getTrustAccount: (id: string) => client.get<TrustAccount>(`/owners/trust-accounts/${id}`),
  createTrustAccount: (data: TrustAccountCreate) =>
    client.post<TrustAccount>('/owners/trust-accounts', data),
  updateTrustAccount: (id: string, data: TrustAccountUpdate) =>
    client.patch<TrustAccount>(`/owners/trust-accounts/${id}`, data),
  reviewTrustAccount: (id: string, data: { compliance_status: string; notes?: string | null }) =>
    client.post<TrustAccount>(`/owners/trust-accounts/${id}/review`, data),
  deleteTrustAccount: (id: string) => client.delete(`/owners/trust-accounts/${id}`),
};
