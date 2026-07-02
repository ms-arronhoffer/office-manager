// ─── Auth ─────────────────────────────────────────────────────────────────────
export interface User {
  id: string;
  organization_id?: string;
  email: string;
  display_name: string;
  auth_provider: string;
  role: 'admin' | 'editor' | 'viewer' | 'accountant';
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
  owner_same_as_landlord?: boolean;
  owner_name?: string;
  owner_company?: string;
  owner_email?: string;
  owner_phone?: string;
  owner_address_line_1?: string;
  owner_address_line_2?: string;
  owner_city?: string;
  owner_state?: string;
  owner_zip_code?: string;
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
  owner_same_as_landlord?: boolean;
  owner_name?: string;
  owner_company?: string;
  owner_email?: string;
  owner_phone?: string;
  owner_address_line_1?: string;
  owner_address_line_2?: string;
  owner_city?: string;
  owner_state?: string;
  owner_zip_code?: string;
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
  contact_type?: string;
  is_primary?: boolean;
  email?: string;
  phone?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface LandlordOfficeRef {
  id: string;
  location_name: string;
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
  secondary_phone?: string;
  fax?: string;
  website?: string;
  online_sign_in?: string;
  entity_type?: string;
  tax_id?: string;
  management_company?: string;
  management_company_id?: string;
  management_company_ref?: ManagementCompanyRef;
  preferred_payment_method?: string;
  payment_terms?: string;
  vendor_id?: string;
  notes?: string;
  additional_names?: LandlordAdditionalName[];
  contacts?: LandlordContact[];
  owned_offices?: LandlordOfficeRef[];
  created_at: string;
  updated_at: string;
}

export interface LandlordCreate {
  ern?: string;
  office_name?: string;
  office_ids?: string[];
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
  secondary_phone?: string;
  fax?: string;
  website?: string;
  online_sign_in?: string;
  entity_type?: string;
  tax_id?: string;
  management_company?: string;
  management_company_id?: string | null;
  preferred_payment_method?: string;
  payment_terms?: string;
  vendor_id?: string;
  notes?: string;
}

export interface LandlordUpdate extends Partial<LandlordCreate> {}

// ─── Management Company ───────────────────────────────────────────────────────
export interface ManagementCompanyRef {
  id: string;
  name: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  website?: string;
  portal_url?: string;
}

export interface ManagementCompany {
  id: string;
  name: string;
  contact_name?: string;
  contact_title?: string;
  contact_email?: string;
  contact_phone?: string;
  secondary_phone?: string;
  fax?: string;
  website?: string;
  portal_url?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface ManagementCompanyCreate {
  name: string;
  contact_name?: string;
  contact_title?: string;
  contact_email?: string;
  contact_phone?: string;
  secondary_phone?: string;
  fax?: string;
  website?: string;
  portal_url?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  notes?: string;
}

export interface ManagementCompanyUpdate extends Partial<ManagementCompanyCreate> {}

// ─── Entity Contact (reusable across entities) ────────────────────────────────
export type EntityContactType = 'landlord' | 'vendor' | 'management_company';

export interface EntityContact {
  id: string;
  entity_type: EntityContactType;
  entity_id: string;
  contact_name: string;
  title?: string;
  contact_type?: string;
  department?: string;
  is_primary: boolean;
  email?: string;
  phone?: string;
  mobile?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface EntityContactCreate {
  entity_type: EntityContactType;
  entity_id: string;
  contact_name: string;
  title?: string;
  contact_type?: string;
  department?: string;
  is_primary?: boolean;
  email?: string;
  phone?: string;
  mobile?: string;
  notes?: string;
}

export interface EntityContactUpdate {
  contact_name?: string;
  title?: string;
  contact_type?: string;
  department?: string;
  is_primary?: boolean;
  email?: string;
  phone?: string;
  mobile?: string;
  notes?: string;
}

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
  refrigerant_type?: string;
  tonnage?: number;
  seer_rating?: number;
  filter_size?: string;
  warranty_expiration?: string;
  last_service_date?: string;
  next_service_date?: string;
  status?: string;
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

// ─── General Ledger ──────────────────────────────────────────────────────────
export interface GLAccount {
  id: string;
  code: string;
  name: string;
  type: string;
  normal_balance: string;
  is_active: boolean;
}

export interface GLAccountCreate {
  code: string;
  name: string;
  type: string;
}

export interface AccountingPeriod {
  id: string;
  year: number;
  month: number;
  status: string;
  closed_at: string | null;
  closed_by_id: string | null;
}

export interface JournalLine {
  id: string;
  account_id: string;
  account_code: string;
  account_name: string;
  line_number: number;
  debit: number;
  credit: number;
  memo: string | null;
}

export interface JournalEntry {
  id: string;
  entry_date: string;
  memo: string | null;
  source: string;
  source_ref: string | null;
  status: string;
  posted_at: string | null;
  lines: JournalLine[];
}

export interface JournalLineInput {
  account_id: string;
  debit: string;
  credit: string;
  memo?: string | null;
}

export interface JournalEntryCreate {
  entry_date: string;
  memo?: string | null;
  lines: JournalLineInput[];
}

export interface TrialBalanceRow {
  account_id: string;
  code: string;
  name: string;
  type: string;
  debit: number;
  credit: number;
  balance: number;
  balance_side: string;
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
  location_hours: string | null;
  technician_name: string | null;
  scheduled_date: string | null;
  estimated_duration_minutes: number | null;
  vendor_completion_notes: string | null;
  vendor_completed_at: string | null;
  created_at: string;
  office: { id: string; location_name: string | null } | null;
}

export interface PortalTicketUpdate {
  description?: string;
  location_hours?: string;
  technician_name?: string;
  scheduled_date?: string | null;
  estimated_duration_minutes?: number | null;
  vendor_completion_notes?: string;
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

export interface VendorPortalCOI {
  id: string;
  certificate_type: string;
  insurer: string | null;
  policy_number: string | null;
  effective_date: string | null;
  expiration_date: string | null;
  limits: string | null;
  certificate_holder: string | null;
  notes: string | null;
  is_verified: boolean;
  status: 'active' | 'expiring_soon' | 'expired' | 'unknown';
  created_at: string;
  updated_at: string;
}

// ─── Client Portal (landlord / management company self-service) ───────────────
export type ClientPortalEntityType = 'landlord' | 'management_company';

export interface ClientPortalInviteResponse {
  signup_token: string;
  signup_url: string;
  expires_at: string;
  activated: boolean;
}

export interface ClientPortalSession {
  portal_token: string;
  portal_url: string;
  expires_at: string;
  entity_type: ClientPortalEntityType;
}

export interface ClientPortalProfile {
  entity_type: ClientPortalEntityType;
  entity_id: string;
  name: string | null;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  address: string | null;
  website: string | null;
}

export type ClientPortalChangeRequestStatus = 'pending' | 'approved' | 'rejected';

export interface ClientPortalChangeRequest {
  id: string;
  entity_type: ClientPortalEntityType;
  entity_id: string;
  status: ClientPortalChangeRequestStatus;
  proposed_changes: Record<string, string | null>;
  message: string | null;
  reviewed_by_display_name: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
}

export interface ClientPortalChangeRequestCreate {
  proposed_changes: Record<string, string | null>;
  message?: string;
}

export interface ClientPortalSummary {
  office_count: number;
  lease_count: number;
  expiring_soon: number;
  open_tickets: number;
}

export interface ClientPortalOffice {
  id: string;
  office_number: number;
  location_name: string;
  location_type: string | null;
  is_active: boolean;
  address_line_1: string | null;
  address_line_2: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  lease_count: number;
}

export interface ClientPortalLease {
  id: string;
  lease_name: string;
  office_id: string | null;
  office_name: string | null;
  lessor_name: string | null;
  lease_commencement_date: string | null;
  lease_expiration: string | null;
  lease_notice_date: string | null;
  notice_given_date: string | null;
  notice_period: string | null;
  expiring_soon: boolean;
}

export interface ClientPortalTicket {
  id: string;
  subject: string;
  status: string;
  priority: string;
  office_id: string | null;
  office_name: string | null;
  scheduled_date: string | null;
  created_at: string;
}

export type ClientPortalStatusValue =
  | 'none'
  | 'invited'
  | 'active'
  | 'revoked'
  | 'expired';

export interface ClientPortalStatus {
  exists: boolean;
  status: ClientPortalStatusValue;
  activated_at: string | null;
  last_active_at: string | null;
  revoked_at: string | null;
  portal_token_expires_at: string | null;
  pending_change_requests: number;
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
  route?: string;
}

export interface AssistantActionProposal {
  method: string;
  endpoint: string;
  body: Record<string, unknown>;
  description: string;
}

export interface AssistantResponse {
  intent: string;
  action_type: 'navigate' | 'search' | 'action' | 'none';
  route?: string | null;
  query?: string | null;
  proposal?: AssistantActionProposal | null;
  confirmation_required: boolean;
  permitted: boolean;
  message: string;
  model: string;
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

// ─── Email Rules ──────────────────────────────────────────────────────────────
export interface EmailReminderRule {
  id: string;
  rule_name: string;
  rule_type: string;
  days_before: number;
  recipient_emails: string[];
  recipient_roles?: string[] | null;
  recipient_user_ids?: string[] | null;
  delivery_mode: string;
  escalation_offsets?: number[] | null;
  escalation_recipient_emails?: string[] | null;
  require_acknowledgement: boolean;
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
  recipient_roles?: string[] | null;
  recipient_user_ids?: string[] | null;
  delivery_mode?: string;
  escalation_offsets?: number[] | null;
  escalation_recipient_emails?: string[] | null;
  require_acknowledgement?: boolean;
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

// ─── Lease Abstract ───────────────────────────────────────────────────────────
export type AbstractFieldType =
  | 'text'
  | 'textarea'
  | 'date'
  | 'currency'
  | 'number'
  | 'percent'
  | 'boolean'
  | 'select';

export type AbstractClauseStatus = 'contains_content' | 'needs_content' | 'incomplete';

export interface AbstractFieldSchema {
  key: string;
  label: string;
  type: AbstractFieldType;
  options?: string[];
}

export interface AbstractClause {
  category_key: string;
  name: string;
  group: string;
  order: number;
  fields: AbstractFieldSchema[];
  status: AbstractClauseStatus;
  content?: Record<string, unknown> | null;
  notes?: string | null;
  updated_at?: string | null;
}

export interface AbstractSummary {
  total: number;
  contains_content: number;
  needs_content: number;
  incomplete: number;
}

export interface LeaseAbstractResponse {
  lease_id: string;
  clauses: AbstractClause[];
  summary: AbstractSummary;
}

export interface AbstractClauseUpdate {
  content?: Record<string, unknown> | null;
  notes?: string | null;
  status?: AbstractClauseStatus;
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

// ─── AI assist (Google Gemini) ───────────────────────────────────────────────
export interface AIStatus {
  configured: boolean;
  model: string;
  period?: string;
  input_tokens_used?: number;
  output_tokens_used?: number;
  input_token_limit?: number | null;
  output_token_limit?: number | null;
  token_limit_reached?: boolean;
}

export interface LeaseParseResult {
  suggested: Record<string, unknown>;
  model: string;
}

export interface AbstractSuggestResult {
  suggested: Record<string, unknown>;
  model: string;
}

export interface DocumentClassifyEntityMatch {
  entity_type: 'vendor' | 'landlord' | 'lease';
  id: string;
  name: string;
}

export interface DocumentClassifyResult {
  document_type: 'vendor_invoice' | 'insurance_certificate' | 'lease_amendment' | 'lease' | 'unknown';
  confidence: 'high' | 'medium' | 'low';
  reasoning: string;
  fields: Record<string, unknown>;
  suggested_matches: DocumentClassifyEntityMatch[];
  model: string;
}

export interface TicketTriageSuggestion {
  category_id?: string | null;
  category_name?: string | null;
  priority?: string | null;
  vendor_id?: string | null;
  vendor_name?: string | null;
  reasoning?: string | null;
  draft_response?: string | null;
}

export interface TicketTriageResult {
  suggested: TicketTriageSuggestion;
  model: string;
}

export interface AIRecommendedAction {
  title: string;
  detail: string;
  priority: string;
  category: string;
}

export interface DocumentParseResult {
  suggested: Record<string, unknown>;
  model: string;
}

export interface AISummaryResult {
  period: string;
  period_label: string;
  narrative: string;
  narrative_html: string;
  recommended_actions: AIRecommendedAction[];
  data: Record<string, unknown>;
  model: string;
}

export interface SimilarTicketMatch {
  id: string;
  subject: string;
  status: string;
  priority: string;
  score: number;
  created_at: string;
}

export interface SimilarTicketsResult {
  matches: SimilarTicketMatch[];
  mode: 'semantic' | 'keyword';
}

export interface AssistantCitation {
  index: number;
  source_type: string;
  source_id: string | null;
  title: string;
  reference: string | null;
  snippet: string;
  score: number;
}

export interface AssistantQueryResult {
  answer: string;
  answer_html: string;
  citations: AssistantCitation[];
  mode: 'semantic' | 'keyword';
  model: string;
}

export interface AssistantReindexResult {
  indexed: number;
}

export interface LeaseDocumentSearchMatch {
  lease_id: string;
  lease_name: string | null;
  attachment_id: string | null;
  source_filename: string;
  chunk_index: number | null;
  snippet: string;
  score: number;
  match_type: string;
}

export interface LeaseDocumentSearchResult {
  query: string;
  matches: LeaseDocumentSearchMatch[];
}

export interface LeaseIndexedDocument {
  attachment_id: string | null;
  source_filename: string;
  chunk_count: number;
}

export interface LeaseIndexedDocumentsResult {
  lease_id: string;
  documents: LeaseIndexedDocument[];
}

export interface LeaseDocumentTextResult {
  attachment_id: string;
  source_filename: string;
  content_type: string | null;
  text: string | null;
  extractable: boolean;
}

export interface PortfolioCitation {
  index: number;
  lease_id: string;
  lease_name: string | null;
  attachment_id: string | null;
  source_filename: string;
  chunk_index: number | null;
  snippet: string;
  score: number;
  match_type: string;
}

export interface PortfolioAskResult {
  question: string;
  answer: string;
  answer_html: string;
  citations: PortfolioCitation[];
  grounded: boolean;
  model: string;
}

// ─── Digital Waivers ──────────────────────────────────────────────────────────
export type WaiverRecipientType = 'contact' | 'visitor';
export type WaiverStatus = 'sent' | 'viewed' | 'signed' | 'declined' | 'expired';

export interface WaiverTemplate {
  id: string;
  name: string;
  description: string | null;
  body: string;
  is_prebuilt: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WaiverTemplateCreate {
  name: string;
  description?: string | null;
  body: string;
}

export interface WaiverTemplateUpdate {
  name?: string;
  description?: string | null;
  body?: string;
  is_active?: boolean;
}

export interface WaiverRequestItem {
  id: string;
  template_id: string | null;
  recipient_type: WaiverRecipientType;
  recipient_name: string | null;
  recipient_email: string;
  entity_contact_id: string | null;
  title: string;
  status: WaiverStatus;
  document_hash: string;
  sign_url: string | null;
  expires_at: string | null;
  sent_at: string | null;
  viewed_at: string | null;
  signed_at: string | null;
  declined_at: string | null;
  created_at: string;
}

export interface SendWaiverRequest {
  template_id: string;
  recipient_type: WaiverRecipientType;
  recipient_email: string;
  recipient_name?: string | null;
  entity_contact_id?: string | null;
  force?: boolean;
}

export interface WaiverRecipientSuggestion {
  name: string | null;
  email: string;
  source: 'contact' | 'waiver';
}

export interface WaiverDuplicateCheck {
  has_pending: boolean;
  pending: WaiverRequestItem[];
  history: WaiverRequestItem[];
}

export interface PublicWaiverView {
  title: string;
  body: string;
  status: WaiverStatus;
  recipient_name: string | null;
  recipient_type: WaiverRecipientType;
  organization_name: string | null;
  consent_text: string;
  expired: boolean;
}

export interface WaiverSignSubmission {
  signer_name: string;
  signer_email?: string | null;
  signature_type: 'typed' | 'drawn';
  signature_data: string;
  consent_agreed: boolean;
  visitor_details?: { label: string; value: string }[] | null;
}

// ─── Maintenance program ──────────────────────────────────────────────────────

export interface MaintenanceVendorSummary {
  id: string;
  company_name: string;
}

export interface MaintenanceOfficeSummary {
  id: string;
  location_name: string;
}

export interface MaintenanceCatalogSubtopic {
  value: string;
  label: string;
}

export interface MaintenanceCatalogCategory {
  value: string;
  label: string;
  subtopics: MaintenanceCatalogSubtopic[];
}

export interface MaintenanceCatalog {
  categories: MaintenanceCatalogCategory[];
  frequencies: string[];
  task_statuses: string[];
  asset_statuses: string[];
}

export interface MaintenanceAsset {
  id: string;
  organization_id: string | null;
  category: string;
  subtopic: string | null;
  office_id: string | null;
  name: string;
  location_desc: string | null;
  make: string | null;
  model: string | null;
  serial_number: string | null;
  install_date: string | null;
  vendor_id: string | null;
  is_regulatory: boolean;
  certification_expiry: string | null;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  vendor: MaintenanceVendorSummary | null;
  office: MaintenanceOfficeSummary | null;
}

export interface MaintenanceTask {
  id: string;
  organization_id: string | null;
  asset_id: string | null;
  category: string;
  subtopic: string | null;
  office_id: string | null;
  title: string;
  description: string | null;
  frequency: string | null;
  last_completed_date: string | null;
  next_due_date: string | null;
  vendor_id: string | null;
  status: string;
  is_regulatory: boolean;
  reminder_enabled: boolean;
  reminder_days_before: number;
  reminder_recipients: string[];
  auto_generate_work_order: boolean;
  work_order_lead_days: number;
  last_generated_due_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  vendor: MaintenanceVendorSummary | null;
  office: MaintenanceOfficeSummary | null;
  computed_status: string;
}

export interface MaintenanceLog {
  id: string;
  task_id: string | null;
  asset_id: string | null;
  service_date: string | null;
  performed_by: string | null;
  vendor_id: string | null;
  cost: number | null;
  invoice_number: string | null;
  description: string;
  status: string | null;
  created_at: string;
  vendor: MaintenanceVendorSummary | null;
}

export interface MaintenanceOverviewCategoryStat {
  category: string;
  label: string;
  task_count: number;
  asset_count: number;
  overdue: number;
  due_soon: number;
}

export interface MaintenanceOverview {
  total_tasks: number;
  total_assets: number;
  overdue: number;
  due_soon: number;
  expiring_certifications: number;
  by_category: MaintenanceOverviewCategoryStat[];
}

export interface MaintenanceComplianceCategoryStat {
  category: string;
  label: string;
  active: number;
  overdue: number;
  regulatory_active: number;
  regulatory_overdue: number;
  on_time_rate: number;
}

export interface MaintenanceCompliance {
  active_tasks: number;
  overdue: number;
  on_time: number;
  on_time_rate: number;
  regulatory_active: number;
  regulatory_overdue: number;
  regulatory_on_time_rate: number;
  automation_enabled: number;
  work_orders_generated: number;
  by_category: MaintenanceComplianceCategoryStat[];
}

export interface GenerateWorkOrderResult {
  ticket_id: string | null;
  created: boolean;
  detail: string;
}

// ─── CAM Reconciliation (Phase 3) ────────────────────────────────────────────
export interface CamLine {
  id: string;
  line_number: number;
  category: string;
  controllable: boolean;
  gross_up_eligible: boolean;
  actual_amount: number;
  grossed_up_amount: number;
}

export interface CamReconciliation {
  id: string;
  organization_id: string | null;
  lease_id: string;
  year: number;
  pro_rata_share: number | null;
  rentable_sqft: number | null;
  building_sqft: number | null;
  gross_up_percent: number | null;
  occupancy_percent: number | null;
  base_year_amount: number | null;
  expense_stop_psf: number | null;
  cap_percent: number | null;
  cap_type: string | null;
  cap_base_year: number | null;
  cap_base_amount: number | null;
  estimated_paid: number;
  total_pool: number;
  controllable_pool: number;
  noncontrollable_pool: number;
  tenant_share_amount: number;
  cap_applied: number;
  offset_amount: number;
  recoverable_amount: number;
  balance_due: number;
  status: string;
  finalized_at: string | null;
  journal_entry_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  lines: CamLine[];
}

export interface CamLineInput {
  category: string;
  actual_amount: number;
  controllable?: boolean | null;
  gross_up_eligible?: boolean | null;
}

export interface CamReconciliationCreate {
  lease_id: string;
  year: number;
  pro_rata_share?: number | null;
  rentable_sqft?: number | null;
  building_sqft?: number | null;
  gross_up_percent?: number | null;
  occupancy_percent?: number | null;
  base_year_amount?: number | null;
  expense_stop_psf?: number | null;
  cap_percent?: number | null;
  cap_type?: string | null;
  cap_base_year?: number | null;
  cap_base_amount?: number | null;
  estimated_paid?: number;
  notes?: string | null;
  lines?: CamLineInput[] | null;
}

export type CamReconciliationUpdate = Partial<Omit<CamReconciliationCreate, 'lease_id' | 'year'>>;

export interface CamAnomaly {
  category: string;
  anomaly_type: string;
  severity: string;
  message: string;
  recommendation: string;
}

export interface CamReviewResponse {
  reconciliation_id: string;
  year: number;
  prior_year: number | null;
  summary: string;
  anomalies: CamAnomaly[];
  model: string;
}

// ─── Accounts Payable (Phase 5) ──────────────────────────────────────────────
export interface BillLine {
  id: string;
  account_id: string;
  line_number: number;
  description: string | null;
  amount: number;
}

export interface BillPayment {
  id: string;
  bill_id: string;
  payment_date: string;
  amount: number;
  method: string | null;
  reference: string | null;
  memo: string | null;
  journal_entry_id: string | null;
  created_at: string;
}

export interface VendorBill {
  id: string;
  organization_id: string | null;
  vendor_id: string;
  bill_number: string | null;
  bill_date: string;
  due_date: string | null;
  currency: string;
  memo: string | null;
  total_amount: number;
  amount_paid: number;
  balance_due: number;
  payment_state: string;
  status: string;
  finalized_at: string | null;
  journal_entry_id: string | null;
  created_at: string;
  updated_at: string;
  lines: BillLine[];
  payments: BillPayment[];
}

export interface BillLineInput {
  account_id: string;
  amount: number;
  description?: string | null;
}

export interface BillCreate {
  vendor_id: string;
  bill_date: string;
  due_date?: string | null;
  bill_number?: string | null;
  currency?: string;
  memo?: string | null;
  lines: BillLineInput[];
}

export type BillUpdate = Partial<Omit<BillCreate, 'vendor_id'>>;

export interface PaymentCreate {
  payment_date: string;
  amount: number;
  method?: string | null;
  reference?: string | null;
  memo?: string | null;
}

// ─── Accounts Receivable (Phase 1.1) ─────────────────────────────────────────
export interface Customer {
  id: string;
  organization_id: string | null;
  name: string;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  address_line_1: string | null;
  address_line_2: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomerCreate {
  name: string;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  address_line_1?: string | null;
  address_line_2?: string | null;
  city?: string | null;
  state?: string | null;
  zip_code?: string | null;
  notes?: string | null;
}

export type CustomerUpdate = Partial<CustomerCreate>;

export interface InvoiceLine {
  id: string;
  account_id: string;
  line_number: number;
  description: string | null;
  amount: number;
}

export interface CustomerReceipt {
  id: string;
  invoice_id: string;
  receipt_date: string;
  amount: number;
  method: string | null;
  reference: string | null;
  memo: string | null;
  journal_entry_id: string | null;
  created_at: string;
}

export interface CustomerInvoice {
  id: string;
  organization_id: string | null;
  customer_id: string;
  invoice_number: string | null;
  invoice_date: string;
  due_date: string | null;
  currency: string;
  memo: string | null;
  total_amount: number;
  amount_received: number;
  balance_due: number;
  receipt_state: string;
  status: string;
  source: string | null;
  source_ref: string | null;
  finalized_at: string | null;
  journal_entry_id: string | null;
  created_at: string;
  updated_at: string;
  lines: InvoiceLine[];
  receipts: CustomerReceipt[];
}

export interface InvoiceLineInput {
  account_id: string;
  amount: number;
  description?: string | null;
}

export interface InvoiceCreate {
  customer_id: string;
  invoice_date: string;
  due_date?: string | null;
  invoice_number?: string | null;
  currency?: string;
  memo?: string | null;
  lines: InvoiceLineInput[];
}

export type InvoiceUpdate = Partial<Omit<InvoiceCreate, 'customer_id'>>;

export interface ReceiptCreate {
  receipt_date: string;
  amount: number;
  method?: string | null;
  reference?: string | null;
  memo?: string | null;
}

export interface AgingInvoice {
  invoice_id: string;
  invoice_number: string | null;
  invoice_date: string;
  due_date: string | null;
  balance_due: number;
  bucket: string;
}

export interface AgingCustomerRow {
  customer_id: string;
  customer_name: string | null;
  buckets: Record<string, number>;
  total: number;
  invoices: AgingInvoice[];
}

export interface ArAgingReport {
  as_of: string;
  buckets: string[];
  customers: AgingCustomerRow[];
  totals: Record<string, number>;
  grand_total: number;
}

// ─── Tax / 1099 (Phase 1.3) ──────────────────────────────────────────────────
export interface Tax1099Box {
  box: string;
  form: string;
  label: string;
  amount: number;
}

export interface Vendor1099Summary {
  vendor_id: string;
  vendor_name: string;
  legal_name: string;
  tax_id: string | null;
  tax_id_type: string | null;
  tax_classification: string | null;
  total: number;
  payment_count: number;
  meets_threshold: boolean;
  boxes: Tax1099Box[];
}

export interface Payment1099 {
  payment_id: string;
  payment_date: string;
  amount: number;
  reportable: boolean;
  box: string | null;
  reference: string | null;
}

export interface Vendor1099Detail {
  vendor_id: string;
  vendor_name: string;
  legal_name: string;
  tax_id: string | null;
  tax_id_type: string | null;
  tax_classification: string | null;
  year: number;
  total: number;
  boxes: Tax1099Box[];
  payments: Payment1099[];
}

// ─── Bank Reconciliation (Phase 1.2) ─────────────────────────────────────────
export interface BankAccount {
  id: string;
  organization_id: string | null;
  name: string;
  gl_account_id: string;
  gl_account_code: string | null;
  gl_account_name: string | null;
  institution: string | null;
  account_number_last4: string | null;
  currency: string;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface BankAccountCreate {
  name: string;
  gl_account_id: string;
  institution?: string | null;
  account_number_last4?: string | null;
  currency?: string;
  notes?: string | null;
}

export interface BankAccountUpdate {
  name?: string | null;
  gl_account_id?: string | null;
  institution?: string | null;
  account_number_last4?: string | null;
  is_active?: boolean | null;
  notes?: string | null;
}

export interface BankTransaction {
  id: string;
  bank_account_id: string;
  txn_date: string;
  description: string | null;
  amount: number;
  reference: string | null;
  fitid: string | null;
  import_source: string | null;
  status: string;
  reconciliation_id: string | null;
  journal_entry_id: string | null;
  created_at: string;
}

export interface BankTransactionCreate {
  txn_date: string;
  amount: number;
  description?: string | null;
  reference?: string | null;
}

export interface BankImportResult {
  imported: number;
  skipped: number;
  total: number;
  source: string;
}

export interface ReconciliationSummary {
  beginning_balance: number;
  ending_balance: number;
  cleared_deposits: number;
  cleared_withdrawals: number;
  cleared_balance: number;
  difference: number;
  is_balanced: boolean;
  cleared_count: number;
}

export interface BankReconciliation {
  id: string;
  organization_id: string | null;
  bank_account_id: string;
  statement_date: string;
  beginning_balance: number;
  ending_balance: number;
  status: string;
  notes: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  summary: ReconciliationSummary;
}

export interface BankReconciliationCreate {
  statement_date: string;
  ending_balance: number;
  beginning_balance?: number | null;
  notes?: string | null;
}

export interface ReconciliationReport {
  reconciliation: BankReconciliation;
  cleared_transactions: BankTransaction[];
  outstanding_transactions: BankTransaction[];
  gl_book_balance: number;
}

// ─── Lease Lifecycle Accounting (Phase 4) ────────────────────────────────────
export interface LifecycleEvent {
  id: string;
  organization_id: string | null;
  lease_id: string;
  event_type: string;
  effective_date: string;
  pre_liability: number;
  pre_rou: number;
  new_payment_amount: number | null;
  new_payment_frequency: string | null;
  new_annual_escalation_rate: number | null;
  new_incremental_borrowing_rate: number | null;
  remaining_term_months: number | null;
  new_expiration: string | null;
  remaining_percentage: number | null;
  termination_penalty: number;
  revised_liability: number;
  liability_adjustment: number;
  rou_adjustment: number;
  post_liability: number;
  post_rou: number;
  gain_loss: number;
  status: string;
  finalized_at: string | null;
  journal_entry_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface LifecycleEventCreate {
  lease_id: string;
  event_type: string;
  effective_date: string;
  pre_liability?: number | null;
  pre_rou?: number | null;
  new_payment_amount?: number | null;
  new_payment_frequency?: string | null;
  new_annual_escalation_rate?: number | null;
  new_incremental_borrowing_rate?: number | null;
  remaining_term_months?: number | null;
  new_expiration?: string | null;
  remaining_percentage?: number | null;
  termination_penalty?: number;
  notes?: string | null;
}

export type LifecycleEventUpdate = Partial<Omit<LifecycleEventCreate, 'lease_id' | 'event_type'>>;

// ─── Financial Statements (Phase 6/7) ────────────────────────────────────────
export interface StatementLine {
  account_id: string | null;
  code: string;
  name: string;
  amount: number;
}

export interface IncomeStatementResponse {
  start_date: string | null;
  end_date: string | null;
  revenue: StatementLine[];
  total_revenue: number;
  expenses: StatementLine[];
  total_expenses: number;
  net_income: number;
}

export interface BalanceSheetResponse {
  as_of_date: string | null;
  assets: StatementLine[];
  total_assets: number;
  liabilities: StatementLine[];
  total_liabilities: number;
  equity: StatementLine[];
  total_equity: number;
  liabilities_and_equity: number;
  net_income: number;
  balanced: boolean;
}

export interface CashFlowSection {
  lines: StatementLine[];
  total: number;
}

export interface CashFlowStatementResponse {
  start_date: string | null;
  end_date: string | null;
  operating: CashFlowSection;
  investing: CashFlowSection;
  financing: CashFlowSection;
  net_change_in_cash: number;
  beginning_cash: number;
  ending_cash: number;
}
