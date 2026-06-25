// ─── Auth ─────────────────────────────────────────────────────────────────────
export interface User {
  id: string;
  organization_id?: string;
  email: string;
  display_name: string;
  auth_provider: string;
  role: 'admin' | 'editor' | 'viewer' | 'ticketer';
  is_super_admin: boolean;
  is_active: boolean;
  last_login_at?: string;
  created_at: string;
}

// ─── Organization ─────────────────────────────────────────────────────────────
export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: 'starter' | 'pro' | 'enterprise';
  is_active: boolean;
  max_seats?: number;
  onboarding_complete: boolean;
  stripe_customer_id?: string;
  stripe_subscription_id?: string;
  trial_ends_at?: string;
  created_at: string;
  updated_at: string;
}

export interface OrganizationCreate {
  name: string;
  slug: string;
  plan?: string;
  max_seats?: number;
}

export interface OrganizationUpdate {
  name?: string;
  plan?: string;
  is_active?: boolean;
  max_seats?: number;
  onboarding_complete?: boolean;
}

export interface SignupRequest {
  org_name: string;
  email: string;
  password: string;
  display_name: string;
}

export interface SignupResponse {
  access_token: string;
  token_type: string;
  organization: Organization;
}

export interface BillingSubscription {
  plan: 'starter' | 'pro' | 'enterprise';
  is_active: boolean;
  payment_status: 'active' | 'past_due' | 'canceled';
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  trial_ends_at: string | null;
  max_seats: number | null;
  seat_count: number;
  billing_configured: boolean;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ApiKeyCreate {
  name: string;
  scopes: string[];
  expires_in_days?: number;
}

export interface Webhook {
  id: string;
  organization_id: string | null;
  url: string;
  events: string;
  is_active: boolean;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WebhookCreate {
  url: string;
  events: string;
}

export interface WebhookUpdate {
  url?: string;
  events?: string;
  is_active?: boolean;
}

export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  event_type: string;
  payload_snapshot: string | null;
  status: string;
  response_code: number | null;
  response_body: string | null;
  attempt_count: number;
  next_retry_at: string | null;
  created_at: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

// ─── Manager ──────────────────────────────────────────────────────────────────
export interface Manager {
  id: string;
  name: string;
  email?: string;
  phone?: string;
}

export interface ManagerCreate {
  name: string;
  email?: string;
  phone?: string;
}

// ─── Office ───────────────────────────────────────────────────────────────────
export interface Office {
  id: string;
  office_number: number;
  region_number?: number;
  location_type: string;
  location_name: string;
  manager_id?: string;
  manager?: Manager;
  is_active: boolean;
  mail_shipping?: string;
  notes?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  phone_number?: string;
  fax?: string;
  email?: string;
  other_names?: string;
  sector?: string;
  crown_property_on_site?: string;
  additional_info?: string;
  closing_notes?: string;
  total_sqft?: number;
  usable_sqft?: number;
  headcount_capacity?: number;
  current_headcount?: number;
  space_type?: string;
  created_at: string;
  updated_at: string;
}

export interface OfficeCreate {
  office_number: number;
  region_number?: number;
  location_type: string;
  location_name: string;
  manager_id?: string;
  is_active?: boolean;
  mail_shipping?: string;
  notes?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  phone_number?: string;
  fax?: string;
  email?: string;
  other_names?: string;
  sector?: string;
  total_sqft?: number;
  usable_sqft?: number;
  headcount_capacity?: number;
  current_headcount?: number;
  space_type?: string;
}

export interface OfficeUpdate extends Partial<OfficeCreate> {}

// ─── Lease ────────────────────────────────────────────────────────────────────
export interface LeaseNote {
  id: string;
  lease_id: string;
  note_text: string;
  note_order: number;
  created_at: string;
}

export interface Lease {
  id: string;
  lease_name: string;
  office_id?: string;
  office?: Office;
  manager_id?: string;
  manager?: Manager;
  lessor_name?: string;
  lease_expiration?: string;
  notice_period?: string;
  notice_period_days?: number;
  lease_notice_date?: string;
  notice_given_date?: string;
  quarem_date?: string;
  quarem_status?: string;
  expiration_year?: number;
  notes?: LeaseNote[];
  // ASC 842 / IFRS 16 financial fields
  lease_commencement_date?: string;
  accounting_standard?: string;       // 'asc842' | 'ifrs16' | 'both'
  lease_classification?: string;      // 'operating' | 'finance'
  payment_amount?: number;
  payment_frequency?: string;         // 'monthly' | 'quarterly' | 'annually'
  annual_escalation_rate?: number;    // e.g. 0.03 = 3%
  incremental_borrowing_rate?: number; // e.g. 0.045 = 4.5%
  initial_direct_costs?: number;
  lease_incentives?: number;
  prepaid_rent?: number;
  residual_value_guarantee?: number;
  is_short_term_lease?: boolean;
  is_low_value_lease?: boolean;
  currency?: string;
  created_at: string;
  updated_at: string;
}

export interface LeaseCreate {
  lease_name: string;
  office_id?: string;
  manager_id?: string;
  lessor_name?: string;
  lease_expiration?: string;
  notice_period?: string;
  notice_period_days?: number;
  lease_notice_date?: string;
  notice_given_date?: string;
  quarem_date?: string;
  quarem_status?: string;
  expiration_year?: number;
  // ASC 842 / IFRS 16 financial fields
  lease_commencement_date?: string;
  accounting_standard?: string;
  lease_classification?: string;
  payment_amount?: number;
  payment_frequency?: string;
  annual_escalation_rate?: number;
  incremental_borrowing_rate?: number;
  initial_direct_costs?: number;
  lease_incentives?: number;
  prepaid_rent?: number;
  residual_value_guarantee?: number;
  is_short_term_lease?: boolean;
  is_low_value_lease?: boolean;
  currency?: string;
}

export interface LeaseUpdate extends Partial<LeaseCreate> {}

// ─── Lease Accounting (ASC 842 / IFRS 16) ────────────────────────────────────
export interface LeaseAccountingPeriod {
  period: number;
  date: string;
  opening_liability: number;
  interest: number;
  payment: number;
  principal: number;
  closing_liability: number;
  rou_carrying_value: number;
  lease_cost: number;
  lease_cost_label: string;
}

export interface LeaseMaturityAnalysis {
  year_1: number;
  year_2: number;
  year_3: number;
  year_4: number;
  year_5: number;
  thereafter: number;
  total_undiscounted: number;
  imputed_interest: number;
  present_value: number;
}

export interface LeaseJournalEntry {
  date: string;
  account: string;
  debit?: number;
  credit?: number;
}

export interface LeaseAccountingResponse {
  accounting_standard: string;
  lease_classification: string;
  initial_lease_liability: number;
  initial_rou_asset: number;
  currency: string;
  ibr_annual: number;
  term_months: number;
  schedule: LeaseAccountingPeriod[];
  maturity_analysis: LeaseMaturityAnalysis;
  journal_entries: LeaseJournalEntry[];
  exempt?: boolean;
  exempt_reason?: string;
}

export interface LeasePortfolioItem {
  lease_id: string;
  lease_name: string;
  office_name?: string;
  accounting_standard: string;
  lease_classification: string;
  initial_rou_asset: number;
  initial_lease_liability: number;
  remaining_rou: number;
  remaining_liability: number;
  ibr_annual: number;
  remaining_months: number;
  currency: string;
}

export interface LeasePortfolioResponse {
  leases: LeasePortfolioItem[];
  total_rou: number;
  total_current_liability: number;
  total_noncurrent_liability: number;
  weighted_avg_ibr?: number;
  weighted_avg_remaining_months?: number;
}

// ─── Landlord ─────────────────────────────────────────────────────────────────
export interface LandlordAdditionalName {
  id: string;
  landlord_id?: string;
  vendor_id?: string;
  co_name?: string;
  vendor_name?: string;
  other_names?: string;
  additional_names?: string;
}

export interface LandlordContact {
  id: string;
  landlord_id: string;
  contact_name: string;
  title?: string;
  email?: string;
  phone?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface Landlord {
  id: string;
  ern?: string;
  office_name?: string;
  /** Legacy free-form address (kept for back-compat). */
  address?: string;
  /** Legacy free-form mailing address (kept for back-compat). */
  contact_mailing_address?: string;
  /** Structured property address. */
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  /** Structured mailing address. */
  mailing_address_line_1?: string;
  mailing_address_line_2?: string;
  mailing_city?: string;
  mailing_state?: string;
  mailing_zip_code?: string;
  landlord_company?: string;
  contact_name?: string;
  title?: string;
  contact_email?: string;
  contact_phone?: string;
  online_sign_in?: string;
  vendor_id?: string;
  notes?: string;
  additional_names?: LandlordAdditionalName[];
  contacts?: LandlordContact[];
  created_at: string;
  updated_at: string;
}

export interface LandlordCreate {
  ern?: string;
  office_name?: string;
  address?: string;
  contact_mailing_address?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  mailing_address_line_1?: string;
  mailing_address_line_2?: string;
  mailing_city?: string;
  mailing_state?: string;
  mailing_zip_code?: string;
  landlord_company?: string;
  contact_name?: string;
  title?: string;
  contact_email?: string;
  contact_phone?: string;
  online_sign_in?: string;
  vendor_id?: string;
  notes?: string;
}

export interface LandlordUpdate extends Partial<LandlordCreate> {}

// ─── Vendor ──────────────────────────────────────────────────────────────────
export interface VendorOfficeRef {
  id: string;
  location_name: string;
}

export interface Vendor {
  id: string;
  company_name: string;
  services?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  /** Legacy free-form address (kept for back-compat). */
  address?: string;
  /** Structured address (preferred for new records). */
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  is_preferred: boolean;
  notes?: string;
  offices: VendorOfficeRef[];
  created_at: string;
  updated_at: string;
}

export interface VendorCreate {
  company_name: string;
  services?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  address?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  is_preferred?: boolean;
  notes?: string;
  office_ids?: string[];
}

export interface VendorUpdate extends Partial<VendorCreate> {}

// ─── Transition ───────────────────────────────────────────────────────────────
export interface ChecklistItem {
  id: string;
  transition_id: string;
  item_label: string;
  response?: string;
  additional_notes?: string;
  extra_notes?: string;
  sort_order: number;
  is_complete: boolean;
  created_at: string;
}

export interface Transition {
  id: string;
  office_id?: string;
  office?: Office;
  office_number?: number;
  transition_type: string;
  address?: string;
  new_address?: string;
  status: string;
  sheet_name?: string;
  notes?: string;
  checklist_items?: ChecklistItem[];
  created_at: string;
  updated_at: string;
}

export interface TransitionCreate {
  office_id?: string;
  office_number?: number;
  transition_type: string;
  address?: string;
  new_address?: string;
  status?: string;
  notes?: string;
}

export interface TransitionUpdate extends Partial<TransitionCreate> {}

// ─── HQ HVAC ──────────────────────────────────────────────────────────────────
export interface HeatPumpServiceLog {
  id: string;
  service_date?: string;
  invoice_number?: string;
  cost?: number;
  description: string;
  created_at: string;
}

export interface HeatPump {
  id: string;
  unit_id: string;
  location_desc?: string;
  make?: string;
  model?: string;
  serial_number?: string;
  install_year?: number;
  notes?: string;
  service_logs?: HeatPumpServiceLog[];
  created_at?: string;
}

export interface HvacIssue {
  id: string;
  description?: string;
  issue_date?: string;
  invoice_number?: string;
  cost?: number;
  status?: string;
  created_at: string;
}

export interface PmTask {
  id: string;
  equipment_category: string;
  equipment_id?: string;
  task_description: string;
  frequency?: string;
  can_in_house: boolean;
  last_pm_date?: string;
  next_due_date?: string;
  status: string;
  notes?: string;
}

export interface PmLog {
  id: string;
  timestamp?: string;
  tech_name?: string;
  date_of_visit?: string;
  location?: string;
  equipment_type?: string;
  equipment_id?: string;
  task?: string;
  status?: string;
  notes?: string;
  created_at: string;
}

export interface Backflow {
  id: string;
  location_desc?: string;
  replaced_year?: number;
  last_tested_by?: string;
  last_tested_year?: number;
  reported_to?: string;
  notes?: string;
}

export interface MaintenanceContract {
  id: string;
  contractor_name?: string;
  contract_start_date?: string;
  cancellation_notice?: string;
  equipment_covered?: string;
  notes?: string;
}

// ─── HVAC Contracts ───────────────────────────────────────────────────────────
export interface HvacOfficeDetail {
  id: string;
  sheet_name?: string;
  hvac_contractor?: string;
  contractor_phone?: string;
  contractor_email?: string;
  contractor_address?: string;
  frequency?: string;
  responsibility_summary?: string;
  responsibility_detail?: string;
  lease_expiration_text?: string;
  lease_expiration?: string;
  notes?: string;
}

export interface HvacContract {
  id: string;
  office_id?: string;
  office_number?: number;
  office_name?: string;
  hvac_company?: string;
  contact?: string;
  comments?: string;
  frequency?: string;
  last_serviced?: string;
  last_serviced_date?: string;
  next_service?: string;
  next_service_date?: string;
  manager_id?: string;
  manager?: Manager;
  landlord_handles: boolean;
  details?: HvacOfficeDetail[];
  created_at: string;
  updated_at: string;
}

export interface HvacContractCreate {
  office_id?: string;
  office_number?: number;
  office_name?: string;
  hvac_company?: string;
  contact?: string;
  comments?: string;
  frequency?: string;
  last_serviced?: string;
  next_service?: string;
  manager_id?: string;
  landlord_handles?: boolean;
}

export interface HvacContractUpdate extends Partial<HvacContractCreate> {}

// ─── Attachments ─────────────────────────────────────────────────────────
export interface Attachment {
  id: string;
  entity_type: string;
  entity_id: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  uploaded_by: string;
  description?: string;
  created_at: string;
}

// ─── Pagination ───────────────────────────────────────────────────────────────
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ─── Dashboard ────────────────────────────────────────────────────────────────
export interface DashboardSummary {
  total_offices: number;
  active_offices: number;
  inactive_offices: number;
  active_leases: number;
  upcoming_expirations_90d: number;
  overdue_notices: number;
  high_priority_tickets: number;
  overdue_tickets: number;
}

export interface LeaseExpirationByYear {
  year: number;
  count: number;
}

export interface TicketVolumeMonth {
  year: number;
  month: number;
  label: string;
  open: number;
  closed: number;
  total: number;
}

export interface TopOfficeByTickets {
  office_id: string;
  office_name: string;
  office_number: number | null;
  ticket_count: number;
}

export interface LeaseRiskBucket {
  bucket: 'expired' | 'critical' | 'warning' | 'healthy';
  count: number;
}

export interface PortfolioHealthScore {
  overall: number;
  lease_health: number;
  ticket_health: number;
  hvac_health: number;
  sla_compliance_pct: number;
  open_high_pct: number;
  lease_expiry_risk_pct: number;
  hvac_overdue_pct: number;
}

export interface OperatingExpense {
  id: string;
  organization_id: string | null;
  lease_id: string;
  year: number;
  category: string;
  budgeted: number | null;
  actual: number | null;
  notes: string | null;
  reconciled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OperatingExpenseCreate {
  lease_id: string;
  year: number;
  category: string;
  budgeted?: number;
  actual?: number;
  notes?: string;
  reconciled_at?: string;
}

export interface OperatingExpenseUpdate {
  year?: number;
  category?: string;
  budgeted?: number;
  actual?: number;
  notes?: string;
  reconciled_at?: string;
}

export interface OperatingExpenseVariance {
  year: number;
  category: string;
  budgeted: number | null;
  actual: number | null;
  variance: number | null;
}

// ─── Vendor Portal ────────────────────────────────────────────────────────────
export interface PortalTokenResponse {
  token: string;
  expires_at: string;
  portal_url: string;
}

export interface PortalTicket {
  id: string;
  subject: string;
  priority: string;
  status: string;
  description: string;
  vendor_completion_notes: string | null;
  vendor_completed_at: string | null;
  created_at: string;
  office: { id: string; location_name: string | null } | null;
}

export interface VendorPortalProfile {
  id: string;
  company_name: string;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  address_line_1: string | null;
  address_line_2: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  services: string | null;
  notes: string | null;
}

// ─── Insurance Certificates ───────────────────────────────────────────────────
export interface InsuranceCertificate {
  id: string;
  organization_id: string | null;
  vendor_id: string | null;
  landlord_id: string | null;
  certificate_type: string;
  insurer: string | null;
  policy_number: string | null;
  effective_date: string | null;
  expiration_date: string | null;
  limits: string | null;
  certificate_holder: string | null;
  notes: string | null;
  is_verified: boolean;
  verified_at: string | null;
  created_at: string;
  updated_at: string;
  status: 'active' | 'expiring_soon' | 'expired' | 'unknown';
  vendor: { id: string; company_name: string } | null;
  landlord: { id: string; company_name: string } | null;
}

export interface InsuranceCertificateCreate {
  vendor_id?: string;
  landlord_id?: string;
  certificate_type: string;
  insurer?: string;
  policy_number?: string;
  effective_date?: string;
  expiration_date?: string;
  limits?: string;
  certificate_holder?: string;
  notes?: string;
}

export interface InsuranceCertificateUpdate {
  certificate_type?: string;
  insurer?: string;
  policy_number?: string;
  effective_date?: string;
  expiration_date?: string;
  limits?: string;
  certificate_holder?: string;
  notes?: string;
  is_verified?: boolean;
}

export interface InsuranceCertComplianceSummary {
  total: number;
  active: number;
  expiring_soon: number;
  expired: number;
  unknown: number;
}

// ─── Phase 3.1: Analytics types ──────────────────────────────────────────────
export interface CostPerSqftRow {
  office_id: string;
  office_name: string;
  office_number: number | null;
  total_sqft: number | null;
  annual_rent: number | null;
  opex_actual: number | null;
  total_annual_cost: number | null;
  cost_per_sqft: number | null;
  opex_by_category: Record<string, number>;
}

export interface MaintenanceSpendMonth {
  year: number;
  month: number;
  label: string;
  labor_total: number;
  materials_total: number;
  grand_total: number;
}

export interface SpaceUtilizationRow {
  office_id: string;
  office_name: string;
  office_number: number | null;
  total_sqft: number | null;
  usable_sqft: number | null;
  headcount_capacity: number | null;
  current_headcount: number | null;
  occupancy_pct: number | null;
  sqft_per_person: number | null;
}

// ─── Phase 3.2: Space History ─────────────────────────────────────────────────
export interface SpaceSnapshot {
  id: string;
  office_id: string;
  snapshot_date: string;
  total_sqft: number | null;
  usable_sqft: number | null;
  headcount_capacity: number | null;
  current_headcount: number | null;
  occupancy_pct: number | null;
  sqft_per_person: number | null;
  space_type: string | null;
  notes: string | null;
  recorded_by_id: string | null;
  created_at: string;
}

export interface SpaceSnapshotCreate {
  snapshot_date?: string;
  total_sqft?: number;
  usable_sqft?: number;
  headcount_capacity?: number;
  current_headcount?: number;
  space_type?: string;
  notes?: string;
}

// ─── Reports ──────────────────────────────────────────────────────────────────
export interface ReportColumn {
  key: string;
  label: string;
}

export interface FilterConfig {
  key: string;
  label: string;
  type: 'text' | 'select' | 'boolean' | 'number';
  options?: { value: string; label: string }[];
}

export interface ReportTemplate {
  id: string;
  title: string;
  columns: ReportColumn[];
  filters_config?: FilterConfig[];
}

export interface ReportRequest {
  dataset: string;
  format: 'pdf' | 'csv' | 'xlsx';
  columns?: string[];
  filters?: Record<string, unknown>;
}

export interface ReportPreviewResponse {
  title: string;
  headers: string[];
  rows: unknown[][];
  total: number;
}

// ─── Ticket Categories ───────────────────────────────────────────────────────
export interface TicketCategory {
  id: string;
  name: string;
  created_at: string;
}

export interface TicketCategoryCreate {
  name: string;
}

// ─── Ticket Notes ───────────────────────────────────────────────────────────
export interface TicketNote {
  id: string;
  note_text: string;
  note_order: number;
  created_at: string;
  created_by_id?: string;
  created_by?: User;
}

// ─── Work Order Cost Lines ────────────────────────────────────────────────────
export interface WorkOrderCostLine {
  id: string;
  ticket_id: string;
  line_type: 'labor' | 'material';
  description: string;
  quantity: number;
  unit_cost: number;
  total_cost: number;
}

export interface WorkOrderCostLineCreate {
  line_type: 'labor' | 'material';
  description: string;
  quantity?: number;
  unit_cost?: number;
}

export interface WorkOrderCostLineUpdate {
  line_type?: 'labor' | 'material';
  description?: string;
  quantity?: number;
  unit_cost?: number;
}

export interface WorkOrderCostSummary {
  labor_total: number;
  materials_total: number;
  grand_total: number;
  lines: WorkOrderCostLine[];
}

// ─── Maintenance Tickets ─────────────────────────────────────────────────────
export interface MaintenanceTicket {
  id: string;
  subject: string;
  priority: 'low' | 'medium' | 'high';
  status: 'open' | 'in_progress' | 'pending_review' | 'closed';
  category_id: string;
  category?: TicketCategory;
  office_id: string;
  office?: Office;
  location_hours?: string;
  description: string;
  created_by_id: string;
  created_by?: User;
  assigned_to_id?: string;
  assigned_to?: Manager;
  vendor_id?: string;
  vendor_completion_notes?: string;
  vendor_completed_at?: string;
  scheduled_date?: string;
  estimated_duration_minutes?: number;
  actual_start_at?: string;
  actual_end_at?: string;
  technician_name?: string;
  notes?: TicketNote[];
  created_at: string;
  updated_at: string;
  closed_at?: string;
}

export interface MaintenanceTicketCreate {
  subject: string;
  priority: string;
  status?: string;
  category_id: string;
  office_id: string;
  location_hours?: string;
  description: string;
  assigned_to_id?: string;
  vendor_id?: string;
  scheduled_date?: string;
  estimated_duration_minutes?: number;
  actual_start_at?: string;
  actual_end_at?: string;
  technician_name?: string;
}

export interface MaintenanceTicketUpdate extends Partial<MaintenanceTicketCreate> {}

// ─── Activity Log ───────────────────────────────────────────────────────────
export interface ActivityLogEntry {
  id: string;
  user_id: string;
  user_display_name: string;
  action: 'created' | 'updated' | 'deleted' | 'status_changed';
  entity_type: string;
  entity_id: string;
  entity_label: string;
  changes?: Record<string, { old: unknown; new: unknown }>;
  created_at: string;
}

// ─── Search ─────────────────────────────────────────────────────────────────
export interface SearchResult {
  entity_type: string;
  entity_id: string;
  label: string;
  sublabel: string;
}

// ─── User Preferences ───────────────────────────────────────────────────────
export interface PinnedOffice {
  id: string;
  label: string;
}

export interface SavedFilter {
  name: string;
  tokens: Array<{ propertyKey?: string; operator?: string; value?: string }>;
  operation: 'and' | 'or';
}

export interface UserPreferences {
  theme: string;
  density: 'comfortable' | 'compact';
  font_size: 'small' | 'medium' | 'large';
  page_sizes: Record<string, number>;
  visible_columns: Record<string, string[]>;
  default_filters: Record<string, Record<string, unknown>>;
  dashboard_widgets: Record<string, boolean>;
  navigation_open: boolean;
  pinned_offices: PinnedOffice[];
  saved_filters: Record<string, SavedFilter[]>;
}

// ─── Wizard Config ──────────────────────────────────────────────────────────
export interface WizardOption {
  label: string;
  value: string;
  next?: string;
}

export interface DisplayColumn {
  key: string;
  header: string;
}

export interface WizardStep {
  id: string;
  type: 'message' | 'text' | 'choice' | 'select' | 'confirm' | 'guidance' | 'display_results';
  text: string;
  field?: string;
  options?: WizardOption[] | string;
  next?: string;
  optional?: boolean;
  followUp?: string;
  // display_results step fields
  endpoint?: string;
  params_from?: string[];
  columns?: DisplayColumn[];
}

export interface WizardConfig {
  id: string;
  name: string;
  description?: string;
  steps: WizardStep[];
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

// ─── Email Rules ──────────────────────────────────────────────────────────────
export interface EmailReminderRule {
  id: string;
  rule_name: string;
  rule_type: string;
  days_before: number;
  recipient_emails: string[];
  is_active: boolean;
  last_triggered_at?: string;
  created_at: string;
  updated_at: string;
}

export interface EmailReminderRuleCreate {
  rule_name: string;
  rule_type: string;
  days_before: number;
  recipient_emails: string[];
  is_active?: boolean;
}

export interface EmailLog {
  id: string;
  rule_id?: string;
  sent_to: string;
  subject: string;
  body?: string;
  sent_at: string;
  status: string;
}

// ─── Ticket Templates ─────────────────────────────────────────────────────────
export interface TicketTemplate {
  id: string;
  name: string;
  subject: string;
  description?: string;
  priority: string;
  category_id?: string;
  category?: TicketCategory;
  office_id?: string;
  office?: Office;
  assigned_to_id?: string;
  assigned_to?: Manager;
  created_at: string;
}

export interface TicketTemplateCreate {
  name: string;
  subject: string;
  description?: string;
  priority?: string;
  category_id?: string;
  office_id?: string;
  assigned_to_id?: string;
}

export interface TicketTemplateUpdate extends Partial<TicketTemplateCreate> {}

// ─── Recurring Ticket Rules ───────────────────────────────────────────────────
export interface RecurringTicketRule {
  id: string;
  name: string;
  subject: string;
  description?: string;
  priority: string;
  category_id?: string;
  category?: TicketCategory;
  office_id?: string;
  office?: Office;
  assigned_to_id?: string;
  assigned_to?: Manager;
  created_by_id?: string;
  created_by?: User;
  frequency: 'daily' | 'weekly' | 'monthly';
  day_of_week?: number;
  day_of_month?: number;
  is_active: boolean;
  last_run_at?: string;
  next_run_at?: string;
  created_at: string;
}

export interface RecurringTicketRuleCreate {
  name: string;
  subject: string;
  description?: string;
  priority?: string;
  category_id?: string;
  office_id?: string;
  assigned_to_id?: string;
  frequency: string;
  day_of_week?: number;
  day_of_month?: number;
}

export interface RecurringTicketRuleUpdate extends Partial<RecurringTicketRuleCreate> {
  is_active?: boolean;
}

// ─── SLA Analytics ────────────────────────────────────────────────────────────
export interface SlaPrioritySummary {
  priority: string;
  total: number;
  breached: number;
  breach_rate: number;
  avg_days_open: number;
}

export interface SlaOfficeRow {
  office: string;
  priority: string;
  total: number;
  breached: number;
  breach_rate: number;
  avg_days_open: number;
}

export interface SlaResolutionRow {
  priority: string;
  resolved_count: number;
  avg_resolution_days: number;
}

export interface SlaAnalyticsResponse {
  open_summary: SlaPrioritySummary[];
  by_office: SlaOfficeRow[];
  sla_thresholds: Record<string, number>;
  resolution_summary?: SlaResolutionRow[];
}

// ─── Lease Options ────────────────────────────────────────────────────────────
export interface LeaseOption {
  id: string;
  lease_id: string;
  option_type: 'renewal' | 'expansion' | 'termination' | 'rofo' | 'rofr' | 'purchase' | string;
  exercise_window_start?: string;
  exercise_window_end?: string;
  notice_required_days?: number;
  new_term_months?: number;
  new_rent_amount?: number;
  status: 'open' | 'exercised' | 'expired' | 'waived';
  notes?: string;
  created_by_id?: string;
  created_at: string;
  updated_at: string;
}

// ─── Rent Roll ────────────────────────────────────────────────────────────────
export interface RentRollRow {
  lease_id: string;
  lease_name: string;
  office_id?: string;
  office_name?: string;
  lessor_name?: string;
  lease_expiration?: string;
  days_to_expiration?: number;
  payment_amount: number;
  payment_frequency: string;
  monthly_rent: number;
  annual_rent: number;
  annual_escalation_rate?: number;
  lease_classification?: string;
  currency: string;
  manager_name?: string;
}

export interface RentRollResponse {
  rows: RentRollRow[];
  total_monthly: number;
  total_annual: number;
  count: number;
}

// ─── Lease Renewals ───────────────────────────────────────────────────────────
export interface LeaseRenewal {
  id: string;
  lease_id: string;
  status: 'in_progress' | 'terms_agreed' | 'executed' | 'abandoned';
  target_expiration?: string;
  new_rent_amount?: number;
  notes?: string;
  notice_sent_at?: string;
  terms_agreed_at?: string;
  executed_at?: string;
  created_by_id?: string;
  created_at: string;
  updated_at: string;
}

// ─── Notifications ────────────────────────────────────────────────────────────
export interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  entity_type: string | null;
  entity_id: string | null;
  is_read: boolean;
  created_at: string;
}
