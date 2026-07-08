import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import DatePicker from '@cloudscape-design/components/date-picker';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import Checkbox from '@cloudscape-design/components/checkbox';
import RadioGroup from '@cloudscape-design/components/radio-group';
import {
  leases as leasesApi,
  offices as officesApi,
  managers as managersApi,
  attachments as attachmentsApi,
  ai as aiApi,
} from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import AILeasePrefill from '@/components/common/AILeasePrefill';
import { EntityQuickCreateSelect } from '@/components/common/EntityQuickCreateSelect';
import { OfficeQuickCreate, ManagerQuickCreate } from '@/components/common/QuickCreateForms';
import type { LeaseCreate, Office, Manager, AbstractFieldSchema } from '@/types';
import { LEASE_STATUS_OPTIONS } from '@/constants/leaseStatus';

type SelectOption = { label: string; value: string };

function subtractDays(dateStr: string, days: number): string {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() - days);
  const yr = dt.getFullYear();
  const mo = String(dt.getMonth() + 1).padStart(2, '0');
  const dy = String(dt.getDate()).padStart(2, '0');
  return `${yr}-${mo}-${dy}`;
}

// Common currency names/aliases → ISO 4217 code (keys upper-cased). A bare
// "DOLLAR"/"DOLLARS" is assumed to mean USD (US-centric app); CAD/AUD callers
// should supply an explicit code or qualified name (mirrors backend).
const CURRENCY_NAME_MAP: Record<string, string> = {
  'US DOLLAR': 'USD',
  'US DOLLARS': 'USD',
  'U.S. DOLLAR': 'USD',
  'UNITED STATES DOLLAR': 'USD',
  DOLLAR: 'USD',
  DOLLARS: 'USD',
  EURO: 'EUR',
  EUROS: 'EUR',
  POUND: 'GBP',
  POUNDS: 'GBP',
  'POUND STERLING': 'GBP',
  'BRITISH POUND': 'GBP',
  STERLING: 'GBP',
  YEN: 'JPY',
  'JAPANESE YEN': 'JPY',
  'CANADIAN DOLLAR': 'CAD',
  'AUSTRALIAN DOLLAR': 'AUD',
  'SWISS FRANC': 'CHF',
  'SWISS FRANCS': 'CHF',
  RUPEE: 'INR',
  'INDIAN RUPEE': 'INR',
  YUAN: 'CNY',
  RENMINBI: 'CNY',
};

// Coerce a free-text / AI-extracted currency value to a 3-letter code so it
// fits the backend's varchar(3) column (mirrors backend normalize_currency_code).
function normalizeCurrencyCode(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const collapsed = value.replace(/\s+/g, ' ').trim().toUpperCase();
  if (!collapsed) return undefined;
  if (/^[A-Z]{3}$/.test(collapsed)) return collapsed;
  const mapped = CURRENCY_NAME_MAP[collapsed];
  if (mapped) return mapped;
  const embedded = collapsed.match(/\b([A-Z]{3})\b/);
  if (embedded) return embedded[1];
  const letters = collapsed.replace(/[^A-Z]/g, '');
  return letters ? letters.slice(0, 3) : undefined;
}

// Trim a free-text / AI-extracted value to the backend column limit so it can
// never overflow the varchar column and 500 the lease create/update request
// (mirrors backend _cap_length in app/schemas/lease.py).
function capLength(value: string | undefined, maxLength: number): string | undefined {
  if (value === undefined) return undefined;
  return value.slice(0, maxLength);
}

/**
 * Map an AI-suggested clause object onto a lease-abstract category's typed
 * fields. Discrete values land in their dedicated fields (coerced to the field
 * type), narrative falls back to the free-text `notes` column. Returns `null`
 * when nothing could be mapped so the caller can skip the update.
 */
function buildClauseUpdate(
  fields: AbstractFieldSchema[],
  suggested: Record<string, unknown>,
): { content: Record<string, unknown>; notes: string | null } | null {
  const content: Record<string, unknown> = {};
  let notes: string | null = null;

  for (const field of fields) {
    const raw = suggested[field.key];
    if (raw === null || raw === undefined) continue;

    if (field.key === 'notes') {
      const text = String(raw).trim();
      if (text) notes = text;
      continue;
    }

    switch (field.type) {
      case 'number':
      case 'currency':
      case 'percent': {
        let n: number;
        if (typeof raw === 'number') {
          n = raw;
        } else {
          // Strip units/symbols; bail out when nothing numeric remains so that
          // non-numeric text (e.g. "N/A") is not silently coerced to 0.
          const cleaned = String(raw).replace(/[^0-9.\-]/g, '');
          if (cleaned === '' || cleaned === '-' || cleaned === '.') break;
          n = Number(cleaned);
        }
        if (Number.isFinite(n)) content[field.key] = n;
        break;
      }
      case 'boolean': {
        if (typeof raw === 'boolean') {
          content[field.key] = raw;
        } else {
          const s = String(raw).trim().toLowerCase();
          if (['true', 'yes', 'y'].includes(s)) content[field.key] = true;
          else if (['false', 'no', 'n'].includes(s)) content[field.key] = false;
        }
        break;
      }
      case 'select': {
        const s = String(raw).trim();
        if (s && (field.options ?? []).includes(s)) content[field.key] = s;
        break;
      }
      default: {
        const s = String(raw).trim();
        if (s) content[field.key] = s;
        break;
      }
    }
  }

  if (Object.keys(content).length === 0 && notes === null) return null;
  return { content, notes };
}


const ACCOUNTING_STD_OPTIONS: SelectOption[] = [
  { label: 'ASC 842 (US GAAP)', value: 'asc842' },
  { label: 'IFRS 16', value: 'ifrs16' },
  { label: 'Both ASC 842 + IFRS 16', value: 'both' },
];

const FREQUENCY_OPTIONS: SelectOption[] = [
  { label: 'Monthly', value: 'monthly' },
  { label: 'Quarterly', value: 'quarterly' },
  { label: 'Annually', value: 'annually' },
];

// Local form state — keeps all values as strings for Input/DatePicker binding
interface LeaseFormState {
  lease_name: string;
  lessor_name: string;
  lease_expiration: string;
  notice_period: string;
  notice_period_days: string;
  lease_notice_date: string;
  notice_given_date: string;
  status: string;
  expiration_year: string;
}

const emptyForm: LeaseFormState = {
  lease_name: '',
  lessor_name: '',
  lease_expiration: '',
  notice_period: '',
  notice_period_days: '',
  lease_notice_date: '',
  notice_given_date: '',
  status: '',
  expiration_year: '',
};

const LeaseFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEditing = !!id;

  const [loading, setLoading] = useState(isEditing);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);
  const [managerOptions, setManagerOptions] = useState<SelectOption[]>([]);

  const [form, setForm] = useState<LeaseFormState>(emptyForm);

  const [selectedOffice, setSelectedOffice] = useState<SelectOption | null>(null);
  const [selectedManager, setSelectedManager] = useState<SelectOption | null>(null);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);
  // The document the user ran AI extraction on; reused to pre-fill the lease
  // abstract after the lease is created (best-effort, Pro+ only).
  const [aiDocument, setAiDocument] = useState<File | null>(null);

  // Accounting / Financial Terms
  const [accountingStandard, setAccountingStandard] = useState<SelectOption | null>(null);
  const [leaseClassification, setLeaseClassification] = useState<string>('operating');
  const [commencementDate, setCommencementDate] = useState<string>('');
  const [paymentAmount, setPaymentAmount] = useState<string>('');
  const [paymentFrequency, setPaymentFrequency] = useState<SelectOption | null>(null);
  const [annualEscalationRate, setAnnualEscalationRate] = useState<string>('');
  const [incrementalBorrowingRate, setIncrementalBorrowingRate] = useState<string>('');
  const [initialDirectCosts, setInitialDirectCosts] = useState<string>('');
  const [leaseIncentives, setLeaseIncentives] = useState<string>('');
  const [prepaidRent, setPrepaidRent] = useState<string>('');
  const [residualValueGuarantee, setResidualValueGuarantee] = useState<string>('');
  const [currency, setCurrency] = useState<string>('USD');
  const [isShortTermLease, setIsShortTermLease] = useState<boolean>(false);
  const [isLowValueLease, setIsLowValueLease] = useState<boolean>(false);

  // Load offices, landlords, managers for select dropdowns
  useEffect(() => {
    const loadOptions = async () => {
      try {
        const [offRes, mgrRes] = await Promise.all([
          officesApi.list({ page_size: 1000 }),
          managersApi.list(),
        ]);
        setOfficeOptions(
          offRes.data.items.map((o: Office) => ({ label: o.location_name, value: String(o.id) })),
        );
        setManagerOptions(
          mgrRes.data.map((m: Manager) => ({ label: m.name, value: String(m.id) })),
        );
      } catch {
        // non-critical — selects will just be empty
      }
    };
    loadOptions();
  }, []);

  // Load existing lease when editing
  useEffect(() => {
    if (!isEditing || !id) return;
    const fetchLease = async () => {
      try {
        const res = await leasesApi.get(id);
        const l = res.data;
        setForm({
          lease_name: l.lease_name,
          lessor_name: l.lessor_name || '',
          lease_expiration: l.lease_expiration || '',
          notice_period: l.notice_period || '',
          notice_period_days: l.notice_period_days != null ? String(l.notice_period_days) : '',
          lease_notice_date: l.lease_notice_date || '',
          notice_given_date: l.notice_given_date || '',
          status: l.status || '',
          expiration_year: l.expiration_year != null ? String(l.expiration_year) : '',
        });
        if (l.office) setSelectedOffice({ label: l.office.location_name, value: String(l.office.id) });
        else if (l.office_id) setSelectedOffice(officeOptions.find((o) => o.value === String(l.office_id)) ?? null);
        if (l.manager) setSelectedManager({ label: l.manager.name, value: String(l.manager.id) });
        // Financial fields
        setAccountingStandard(l.accounting_standard ? (ACCOUNTING_STD_OPTIONS.find((o) => o.value === l.accounting_standard) ?? null) : null);
        setLeaseClassification(l.lease_classification || 'operating');
        setCommencementDate(l.lease_commencement_date || '');
        setPaymentAmount(l.payment_amount != null ? String(l.payment_amount) : '');
        setPaymentFrequency(l.payment_frequency ? (FREQUENCY_OPTIONS.find((o) => o.value === l.payment_frequency) ?? null) : null);
        setAnnualEscalationRate(l.annual_escalation_rate != null ? String(parseFloat(String(l.annual_escalation_rate)) * 100) : '');
        setIncrementalBorrowingRate(l.incremental_borrowing_rate != null ? String(parseFloat(String(l.incremental_borrowing_rate)) * 100) : '');
        setInitialDirectCosts(l.initial_direct_costs != null ? String(l.initial_direct_costs) : '');
        setLeaseIncentives(l.lease_incentives != null ? String(l.lease_incentives) : '');
        setPrepaidRent(l.prepaid_rent != null ? String(l.prepaid_rent) : '');
        setResidualValueGuarantee(l.residual_value_guarantee != null ? String(l.residual_value_guarantee) : '');
        setCurrency(l.currency || 'USD');
        setIsShortTermLease(l.is_short_term_lease || false);
        setIsLowValueLease(l.is_low_value_lease || false);
      } catch {
        setError('Failed to load lease data.');
      } finally {
        setLoading(false);
      }
    };
    fetchLease();
  }, [id, isEditing]);

  /**
   * Best-effort work that runs *after* a lease has been successfully created:
   * upload any queued documents and, when the same document was AI-analysed,
   * pre-fill the lease abstract from it. Returns human-readable warnings for any
   * non-fatal failures so the caller can show them without implying the lease
   * itself failed to save.
   */
  const finalizeLeaseCreation = async (newId: string): Promise<string[]> => {
    const warnings: string[] = [];

    const failed: string[] = [];
    for (const qf of queuedFiles) {
      try {
        await attachmentsApi.upload('lease', newId, qf.file);
      } catch {
        failed.push(qf.file.name);
      }
    }
    if (failed.length > 0) {
      warnings.push(
        `${failed.length} attachment(s) failed to upload (${failed.join(', ')}); re-upload them from the lease page.`,
      );
    }

    // Pre-fill the lease abstract from the AI-analysed document. This requires
    // the AI assist entitlement (Pro+) and a configured provider, so any
    // failure here is silently tolerated and never blocks lease creation.
    if (aiDocument) {
      try {
        const res = await aiApi.suggestAbstract(newId, aiDocument);
        const suggested = res.data.suggested || {};

        // Load the catalog so suggested values can be mapped onto each
        // category's typed fields (and unknown field keys dropped).
        const fieldsByCategory = new Map<string, AbstractFieldSchema[]>();
        try {
          const abstractRes = await leasesApi.getAbstract(newId);
          for (const clause of abstractRes.data.clauses ?? []) {
            fieldsByCategory.set(clause.category_key, clause.fields ?? []);
          }
        } catch {
          // Catalog unavailable: fall back to notes-only below.
        }

        const results = await Promise.allSettled(
          Object.entries(suggested).map(([categoryKey, value]) => {
            const obj = (value ?? {}) as Record<string, unknown>;
            const fields = fieldsByCategory.get(categoryKey);

            let update: { content?: Record<string, unknown> | null; notes?: string | null } | null =
              null;
            if (fields && fields.length > 0) {
              update = buildClauseUpdate(fields, obj);
            } else {
              // No schema available — preserve the legacy summary+notes text.
              const parts = [obj.summary, obj.notes]
                .map((p) => (p === null || p === undefined ? '' : String(p).trim()))
                .filter((p) => p.length > 0);
              const text = parts.join('\n\n');
              if (text) update = { notes: text };
            }
            if (!update) return Promise.resolve(false);
            // Resolve to true on success; swallow unknown-category / transient errors.
            return leasesApi
              .updateAbstractClause(newId, categoryKey, update)
              .then(() => true)
              .catch(() => false);
          }),
        );
        const applied = results.filter(
          (r) => r.status === 'fulfilled' && r.value === true,
        ).length;
        if (applied === 0) {
          warnings.push('No abstract clauses could be pre-filled from the document.');
        }
      } catch {
        // Not entitled / not configured / provider error: leave the abstract empty.
      }
    }

    return warnings;
  };

  const handleSubmit = async () => {
    if (!form.lease_name.trim()) {
      setError('Lease Name is required.');
      return;
    }
    if (!form.expiration_year.trim()) {
      setError('Expiration Year is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: LeaseCreate = {
        lease_name: form.lease_name.trim(),
        office_id: selectedOffice ? selectedOffice.value : undefined,
        manager_id: selectedManager ? selectedManager.value : undefined,
        lessor_name: form.lessor_name.trim() || undefined,
        lease_expiration: form.lease_expiration || undefined,
        notice_period: form.notice_period.trim() || undefined,
        notice_period_days: form.notice_period_days ? parseInt(form.notice_period_days, 10) : undefined,
        lease_notice_date: form.lease_notice_date || undefined,
        notice_given_date: form.notice_given_date || undefined,
        status: form.status || undefined,
        expiration_year: parseInt(form.expiration_year.trim(), 10),
        // Accounting / Financial Terms
        accounting_standard: accountingStandard?.value || undefined,
        lease_classification: accountingStandard?.value && accountingStandard.value !== 'ifrs16' ? leaseClassification || undefined : undefined,
        lease_commencement_date: commencementDate || undefined,
        payment_amount: paymentAmount ? parseFloat(paymentAmount) : undefined,
        payment_frequency: paymentFrequency?.value || undefined,
        annual_escalation_rate: annualEscalationRate ? parseFloat(annualEscalationRate) / 100 : undefined,
        incremental_borrowing_rate: incrementalBorrowingRate ? parseFloat(incrementalBorrowingRate) / 100 : undefined,
        initial_direct_costs: initialDirectCosts ? parseFloat(initialDirectCosts) : undefined,
        lease_incentives: leaseIncentives ? parseFloat(leaseIncentives) : undefined,
        prepaid_rent: prepaidRent ? parseFloat(prepaidRent) : undefined,
        residual_value_guarantee: residualValueGuarantee ? parseFloat(residualValueGuarantee) : undefined,
        currency: currency.trim() || 'USD',
        is_short_term_lease: isShortTermLease,
        is_low_value_lease: isLowValueLease,
      };
      if (isEditing && id) {
        await leasesApi.update(id, payload);
        navigate(`/leases/${id}`);
      } else {
        // The lease itself must be created first. A failure *here* is the only
        // thing that should surface as "Failed to create lease".
        const res = await leasesApi.create(payload);
        const newId = String(res.data.id);

        // Everything below is best-effort post-creation work: attaching the
        // uploaded document(s) and pre-filling the abstract. None of it should
        // make a successfully-created lease look like a failure, so we collect
        // warnings instead of throwing.
        const warnings = await finalizeLeaseCreation(newId);
        if (warnings.length > 0) {
          setError(`Lease created. ${warnings.join(' ')}`);
        }
        navigate(`/leases/${newId}`);
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        `Failed to ${isEditing ? 'update' : 'create'} lease.`;
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  const queueExtractedFile = (file: File) => {
    // Remember the AI-analysed document so we can also pre-fill the lease
    // abstract from it once the lease exists.
    setAiDocument(file);
    setQueuedFiles((prev) => {
      // Avoid duplicating the same document if the user re-runs the extraction.
      if (prev.some((qf) => qf.file.name === file.name && qf.file.size === file.size)) {
        return prev;
      }
      return [...prev, { file, id: `ai-${Date.now()}-${Math.random()}` }];
    });
  };

  const applyAISuggestions = (suggested: Record<string, unknown>) => {
    const str = (v: unknown): string | undefined =>
      v === null || v === undefined ? undefined : String(v);
    // Normalise a money-ish value to a bare numeric string (strip symbols/commas).
    const num = (v: unknown): string | undefined => {
      const s = str(v);
      if (s === undefined) return undefined;
      const cleaned = s.replace(/[^0-9.-]/g, '');
      return cleaned === '' ? undefined : cleaned;
    };
    // The AI returns rates as decimal fractions (0.03); the form edits percent.
    const pct = (v: unknown): string | undefined => {
      const cleaned = num(v);
      if (cleaned === undefined) return undefined;
      const n = parseFloat(cleaned);
      if (Number.isNaN(n)) return undefined;
      // Round to a sensible precision to avoid float noise (e.g. 0.045 -> 4.5).
      return String(Math.round(n * 100 * 1e6) / 1e6);
    };

    setForm((f) => ({
      ...f,
      lease_name: capLength(str(suggested.lease_name), 255) ?? f.lease_name,
      lessor_name: str(suggested.lessor_name) ?? f.lessor_name,
      lease_expiration: str(suggested.lease_expiration) ?? f.lease_expiration,
      notice_period: capLength(str(suggested.notice_period), 255) ?? f.notice_period,
      notice_period_days: num(suggested.notice_period_days) ?? f.notice_period_days,
      lease_notice_date: str(suggested.lease_notice_date) ?? f.lease_notice_date,
      expiration_year: num(suggested.expiration_year) ?? f.expiration_year,
    }));

    const commencement =
      str(suggested.lease_commencement_date) ??
      str(suggested.lease_commencement) ??
      str(suggested.commencement_date);
    if (commencement) setCommencementDate(commencement);

    // ── Financial / accounting terms ──────────────────────────────────────────
    const rent =
      num(suggested.payment_amount) ??
      num(suggested.monthly_rent) ??
      num(suggested.base_rent) ??
      num(suggested.rent);
    if (rent !== undefined) setPaymentAmount(rent);

    const freq = str(suggested.payment_frequency)?.toLowerCase();
    const freqOption = FREQUENCY_OPTIONS.find((o) => o.value === freq);
    if (freqOption) setPaymentFrequency(freqOption);

    const escalation = pct(suggested.annual_escalation_rate);
    if (escalation !== undefined) setAnnualEscalationRate(escalation);

    const borrowing = pct(suggested.incremental_borrowing_rate);
    if (borrowing !== undefined) setIncrementalBorrowingRate(borrowing);

    const idc = num(suggested.initial_direct_costs);
    if (idc !== undefined) setInitialDirectCosts(idc);

    const incentives = num(suggested.lease_incentives);
    if (incentives !== undefined) setLeaseIncentives(incentives);

    const prepaid = num(suggested.prepaid_rent);
    if (prepaid !== undefined) setPrepaidRent(prepaid);

    const residual = num(suggested.residual_value_guarantee);
    if (residual !== undefined) setResidualValueGuarantee(residual);

    const standard = str(suggested.accounting_standard)?.toLowerCase();
    const standardOption = ACCOUNTING_STD_OPTIONS.find((o) => o.value === standard);
    if (standardOption) setAccountingStandard(standardOption);

    const classification = str(suggested.lease_classification)?.toLowerCase();
    if (classification === 'operating' || classification === 'finance') {
      setLeaseClassification(classification);
    }

    const cur = str(suggested.currency);
    if (cur) {
      const code = normalizeCurrencyCode(cur);
      if (code) setCurrency(code);
    }

    if (typeof suggested.is_short_term_lease === 'boolean') {
      setIsShortTermLease(suggested.is_short_term_lease);
    }
    if (typeof suggested.is_low_value_lease === 'boolean') {
      setIsLowValueLease(suggested.is_low_value_lease);
    }
  };

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Home', href: '/' },
              { text: 'Leases', href: '/leases' },
              isEditing
                ? { text: 'Edit Lease', href: `/leases/${id}/edit` }
                : { text: 'Create Lease', href: '/leases/new' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header variant="h1">{isEditing ? 'Edit Lease' : 'Create Lease'}</Header>
        </SpaceBetween>
      }
    >
      {error && (
        <Alert type="error" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate('/leases')}>Cancel</Button>
            <Button variant="primary" loading={saving} onClick={handleSubmit}>
              {isEditing ? 'Save Changes' : 'Create Lease'}
            </Button>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="l">
        {!isEditing && <AILeasePrefill onSuggested={applyAISuggestions} onFileExtracted={queueExtractedFile} />}
        <Container header={<Header variant="h2">Lease Information</Header>}>
          <SpaceBetween size="l">
            <FormField label="Lease Name" constraintText="Required">
              <Input
                value={form.lease_name}
                onChange={({ detail }) => setForm((f) => ({ ...f, lease_name: detail.value }))}
                placeholder="e.g., Downtown Office Lease 2024"
              />
            </FormField>

            <FormField label="Office" stretch>
                <EntityQuickCreateSelect
                  selectedOption={selectedOffice}
                  onChange={(opt) => setSelectedOffice(opt)}
                  options={officeOptions}
                  placeholder="Select office"
                  quickCreate={{
                    label: '+ Add new office…',
                    render: ({ visible, onClose, onCreated }) => (
                      <OfficeQuickCreate visible={visible} onClose={onClose} onCreated={onCreated} />
                    ),
                  }}
                />
              </FormField>

            <FormField
              label="Lessor Name"
              description="Override or supplement the landlord record"
            >
              <Input
                value={form.lessor_name || ''}
                onChange={({ detail }) => setForm((f) => ({ ...f, lessor_name: detail.value }))}
                placeholder="Lessor entity name"
              />
            </FormField>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Expiration Date">
                <DatePicker
                  value={form.lease_expiration || ''}
                  onChange={({ detail }) => {
                    const exp = detail.value;
                    const days = parseInt(form.notice_period_days, 10);
                    const noticeDate = exp && !isNaN(days) && days > 0 ? subtractDays(exp, days) : form.lease_notice_date;
                    const year = exp ? String(new Date(exp).getFullYear()) : form.expiration_year;
                    setForm((f) => ({ ...f, lease_expiration: exp, lease_notice_date: noticeDate, expiration_year: year }));
                  }}
                  placeholder="YYYY/MM/DD"
                  openCalendarAriaLabel={(selectedDate) =>
                    'Choose expiration date' +
                    (selectedDate ? `, selected date is ${selectedDate}` : '')
                  }
                />
              </FormField>
              <FormField label="Notice Period (days)">
                <Input
                  type="number"
                  value={form.notice_period_days}
                  onChange={({ detail }) => {
                    const days = parseInt(detail.value, 10);
                    const noticeDate = form.lease_expiration && !isNaN(days) && days > 0 ? subtractDays(form.lease_expiration, days) : form.lease_notice_date;
                    setForm((f) => ({ ...f, notice_period_days: detail.value, lease_notice_date: noticeDate }));
                  }}
                  placeholder="e.g., 90"
                />
              </FormField>
              <FormField label="Notice Date">
                <DatePicker
                  value={form.lease_notice_date || ''}
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, lease_notice_date: detail.value }))
                  }
                  placeholder="YYYY/MM/DD"
                  openCalendarAriaLabel={(selectedDate) =>
                    'Choose notice date' +
                    (selectedDate ? `, selected date is ${selectedDate}` : '')
                  }
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Notice Given Date">
                <DatePicker
                  value={form.notice_given_date || ''}
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, notice_given_date: detail.value }))
                  }
                  placeholder="YYYY/MM/DD"
                  openCalendarAriaLabel={(selectedDate) =>
                    'Choose notice given date' +
                    (selectedDate ? `, selected date is ${selectedDate}` : '')
                  }
                />
              </FormField>
              <FormField label="Expiration Year" constraintText="Required">
                <Input
                  type="number"
                  value={form.expiration_year}
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, expiration_year: detail.value }))
                  }
                  placeholder="e.g., 2024"
                />
              </FormField>
              <FormField label="Notice Period">
                <Input
                  value={form.notice_period}
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, notice_period: detail.value }))
                  }
                  placeholder="e.g., 90 days"
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Status">
                <Select
                  selectedOption={
                    form.status
                      ? LEASE_STATUS_OPTIONS.find((o) => o.value === form.status) ?? null
                      : null
                  }
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, status: detail.selectedOption.value ?? '' }))
                  }
                  options={LEASE_STATUS_OPTIONS}
                  placeholder="Select status"
                  empty="No statuses"
                />
              </FormField>
            </SpaceBetween>

            <FormField label="Manager">
              <EntityQuickCreateSelect
                selectedOption={selectedManager}
                onChange={(opt) => setSelectedManager(opt)}
                options={managerOptions}
                placeholder="Select manager"
                quickCreate={{
                  label: '+ Add new manager…',
                  render: ({ visible, onClose, onCreated }) => (
                    <ManagerQuickCreate visible={visible} onClose={onClose} onCreated={onCreated} />
                  ),
                }}
              />
            </FormField>

            {!isEditing && (
              <FileQueueField files={queuedFiles} onChange={setQueuedFiles} disabled={saving} />
            )}
          </SpaceBetween>
        </Container>

        <Container header={<Header variant="h2">Accounting / Financial Terms</Header>}>
          <SpaceBetween size="l">
            <FormField label="Accounting Standard" description="Select the applicable accounting standard for lease recognition">
              <Select
                selectedOption={accountingStandard}
                onChange={({ detail }) => setAccountingStandard(detail.selectedOption as SelectOption)}
                options={ACCOUNTING_STD_OPTIONS}
                placeholder="None (no accounting recognition)"
                filteringType="auto"
              />
            </FormField>

            {accountingStandard && accountingStandard.value !== 'ifrs16' && (
              <FormField label="Lease Classification" description="ASC 842 classification (IFRS 16 always uses finance-like treatment)">
                <RadioGroup
                  value={leaseClassification}
                  onChange={({ detail }) => setLeaseClassification(detail.value)}
                  items={[
                    { value: 'operating', label: 'Operating' },
                    { value: 'finance', label: 'Finance' },
                  ]}
                />
              </FormField>
            )}

            <FormField label="Lease Commencement Date" description="Date when lease payments begin (may differ from execution date)">
              <DatePicker
                value={commencementDate}
                onChange={({ detail }) => setCommencementDate(detail.value)}
                placeholder="YYYY/MM/DD"
                openCalendarAriaLabel={(selectedDate) =>
                  'Choose commencement date' + (selectedDate ? `, selected date is ${selectedDate}` : '')
                }
              />
            </FormField>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Payment Amount" description="Cash payment per occurrence (e.g., $5,000/month)">
                <Input
                  type="number"
                  value={paymentAmount}
                  onChange={({ detail }) => setPaymentAmount(detail.value)}
                  placeholder="e.g., 5000"
                />
              </FormField>
              <FormField label="Payment Frequency">
                <Select
                  selectedOption={paymentFrequency}
                  onChange={({ detail }) => setPaymentFrequency(detail.selectedOption as SelectOption)}
                  options={FREQUENCY_OPTIONS}
                  placeholder="Select frequency"
                />
              </FormField>
              <FormField label="Currency">
                <Input
                  value={currency}
                  onChange={({ detail }) => setCurrency(detail.value)}
                  placeholder="USD"
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Annual Escalation Rate (%)" description="e.g., enter 3 for 3% annual increase">
                <Input
                  type="number"
                  value={annualEscalationRate}
                  onChange={({ detail }) => setAnnualEscalationRate(detail.value)}
                  placeholder="e.g., 3.0"
                />
              </FormField>
              <FormField label="Incremental Borrowing Rate (%)" description="e.g., enter 4.5 for 4.5% IBR (required for accounting)">
                <Input
                  type="number"
                  value={incrementalBorrowingRate}
                  onChange={({ detail }) => setIncrementalBorrowingRate(detail.value)}
                  placeholder="e.g., 4.5"
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Initial Direct Costs" description="Capitalized lease origination costs">
                <Input
                  type="number"
                  value={initialDirectCosts}
                  onChange={({ detail }) => setInitialDirectCosts(detail.value)}
                  placeholder="0.00"
                />
              </FormField>
              <FormField label="Lease Incentives / TI Allowances" description="Landlord contributions (reduces ROU asset)">
                <Input
                  type="number"
                  value={leaseIncentives}
                  onChange={({ detail }) => setLeaseIncentives(detail.value)}
                  placeholder="0.00"
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Prepaid Rent" description="Rent paid before commencement (increases ROU asset)">
                <Input
                  type="number"
                  value={prepaidRent}
                  onChange={({ detail }) => setPrepaidRent(detail.value)}
                  placeholder="0.00"
                />
              </FormField>
              <FormField label="Residual Value Guarantee" description="Amount guaranteed at end of term">
                <Input
                  type="number"
                  value={residualValueGuarantee}
                  onChange={({ detail }) => setResidualValueGuarantee(detail.value)}
                  placeholder="0.00"
                />
              </FormField>
            </SpaceBetween>

            <Checkbox
              checked={isShortTermLease}
              onChange={({ detail }) => setIsShortTermLease(detail.checked)}
            >
              Short-term lease (&lt;12 months) — exempt from ROU/Liability recognition
            </Checkbox>

            <Checkbox
              checked={isLowValueLease}
              onChange={({ detail }) => setIsLowValueLease(detail.checked)}
            >
              Low-value lease (IFRS 16 only) — exempt from recognition
            </Checkbox>
          </SpaceBetween>
        </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
};

export default LeaseFormPage;
