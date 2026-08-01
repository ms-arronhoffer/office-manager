import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Wizard from '@cloudscape-design/components/wizard';
import Container from '@cloudscape-design/components/container';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Textarea from '@cloudscape-design/components/textarea';
import DatePicker from '@cloudscape-design/components/date-picker';
import RadioGroup from '@cloudscape-design/components/radio-group';
import Checkbox from '@cloudscape-design/components/checkbox';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import {
  leases as leasesApi,
  offices as officesApi,
  managers as managersApi,
  landlords as landlordsApi,
  attachments as attachmentsApi,
} from '@/api';
import { EntityQuickCreateSelect } from '@/components/common/EntityQuickCreateSelect';
import {
  OfficeQuickCreate,
  ManagerQuickCreate,
  LandlordQuickCreate,
  type QuickCreateOption,
} from '@/components/common/QuickCreateForms';
import { wizardI18nStrings } from '@/components/common/wizardI18n';
import { LEASE_STATUS_OPTIONS } from '@/constants/leaseStatus';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import AILeasePrefill from '@/components/common/AILeasePrefill';
import CamHistoryReviewModal from '@/components/common/CamHistoryReviewModal';
import type { LeaseCreate, Office, Manager, CamHistoryRow, CamHistoryParseResult } from '@/types';
import type { CamHistoryConfirmOptions } from '@/components/common/CamHistoryReviewModal';

const ACCOUNTING_STD_OPTIONS: QuickCreateOption[] = [
  { label: 'ASC 842 (US GAAP)', value: 'asc842' },
  { label: 'IFRS 16', value: 'ifrs16' },
  { label: 'Both ASC 842 + IFRS 16', value: 'both' },
];

const FREQUENCY_OPTIONS: QuickCreateOption[] = [
  { label: 'Monthly', value: 'monthly' },
  { label: 'Quarterly', value: 'quarterly' },
  { label: 'Annually', value: 'annually' },
];

const CLASSIFICATION_OPTIONS: QuickCreateOption[] = [
  { label: 'Operating', value: 'operating' },
  { label: 'Finance', value: 'finance' },
];

type LeaseKind = 'net_new' | 'legacy';

interface HistoryRow {
  id: string;
  target_expiration: string;
  new_rent_amount: string;
  notes: string;
  files: QueuedFile[];
}

function newHistoryRow(): HistoryRow {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    target_expiration: '',
    new_rent_amount: '',
    notes: '',
    files: [],
  };
}

const LeaseWizardPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentLeaseFiles, setCurrentLeaseFiles] = useState<QueuedFile[]>([]);

  // Option lists
  const [officeOptions, setOfficeOptions] = useState<QuickCreateOption[]>([]);
  const [managerOptions, setManagerOptions] = useState<QuickCreateOption[]>([]);
  const [landlordOptions, setLandlordOptions] = useState<QuickCreateOption[]>([]);

  // Step 1 — type & name
  const [leaseKind, setLeaseKind] = useState<LeaseKind>('net_new');
  const [leaseName, setLeaseName] = useState('');

  // Step 2 — property & parties
  const [office, setOffice] = useState<QuickCreateOption | null>(null);
  const [landlord, setLandlord] = useState<QuickCreateOption | null>(null);
  const [manager, setManager] = useState<QuickCreateOption | null>(null);
  const [lessorName, setLessorName] = useState('');

  // Step 3 — term & dates
  const [commencementDate, setCommencementDate] = useState('');
  const [leaseExpiration, setLeaseExpiration] = useState('');
  const [expirationYear, setExpirationYear] = useState('');
  const [status, setStatus] = useState<QuickCreateOption | null>(null);
  const [noticePeriod, setNoticePeriod] = useState('');
  const [noticePeriodDays, setNoticePeriodDays] = useState('');

  // Step 4 — financials
  const [accountingStandard, setAccountingStandard] = useState<QuickCreateOption | null>(null);
  const [leaseClassification, setLeaseClassification] = useState<QuickCreateOption | null>(CLASSIFICATION_OPTIONS[0]);
  const [paymentAmount, setPaymentAmount] = useState('');
  const [paymentFrequency, setPaymentFrequency] = useState<QuickCreateOption | null>(null);
  const [annualEscalationRate, setAnnualEscalationRate] = useState('');
  const [incrementalBorrowingRate, setIncrementalBorrowingRate] = useState('');
  const [initialDirectCosts, setInitialDirectCosts] = useState('');
  const [leaseIncentives, setLeaseIncentives] = useState('');
  const [prepaidRent, setPrepaidRent] = useState('');
  const [residualValueGuarantee, setResidualValueGuarantee] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [isShortTermLease, setIsShortTermLease] = useState(false);
  const [isLowValueLease, setIsLowValueLease] = useState(false);

  // Step 5 — history / renewals
  const [historyRows, setHistoryRows] = useState<HistoryRow[]>([]);

  // Staged CAM history rows from AI extraction (review modal)
  const [stagedCamRows, setStagedCamRows] = useState<CamHistoryRow[]>([]);
  const [stagedCamMeta, setStagedCamMeta] = useState<CamHistoryParseResult | null>(null);
  const [stagedCamPeriodStatus, setStagedCamPeriodStatus] = useState<'auto' | 'historical'>('historical');
  const [camReviewVisible, setCamReviewVisible] = useState(false);
  // Confirmed rows to import after lease is created
  const pendingCamRef = useRef<{ rows: CamHistoryRow[]; options: CamHistoryConfirmOptions } | null>(null);

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    officesApi
      .list({ page_size: 1000 })
      .then((res) =>
        setOfficeOptions(
          res.data.items.map((o: Office) => ({
            label: `${o.office_number} — ${o.location_name}`,
            value: String(o.id),
          })),
        ),
      )
      .catch(() => undefined);
    managersApi
      .list()
      .then((res) =>
        setManagerOptions(res.data.map((m: Manager) => ({ label: m.name, value: String(m.id) }))),
      )
      .catch(() => undefined);
    landlordsApi
      .list({ page_size: 500, sort_by: 'landlord_company' })
      .then((res) =>
        setLandlordOptions(
          res.data.items.map((l) => ({
            label:
              l.landlord_company || l.office_name || l.contact_name || l.ern || 'Unnamed landlord',
            value: String(l.id),
          })),
        ),
      )
      .catch(() => undefined);
  }, []);

  // Carry office context from "Add lease" on an office record into the wizard.
  useEffect(() => {
    const officeId = searchParams.get('office_id');
    if (!officeId || office) return;
    const match = officeOptions.find((o) => o.value === officeId);
    if (match) setOffice(match);
  }, [searchParams, officeOptions, office]);

  const validateTypeAndName = (): boolean => {
    const errs: Record<string, string> = {};
    if (leaseName.trim() === '') errs.lease_name = 'Lease name is required.';
    setFieldErrors((prev) => ({ ...prev, ...errs, ...(errs.lease_name ? {} : { lease_name: '' }) }));
    return !errs.lease_name;
  };

  const validateTerm = (): boolean => {
    const errs: Record<string, string> = {};
    if (expirationYear.trim() === '') {
      errs.expiration_year = 'Expiration year is required.';
    } else if (Number.isNaN(parseInt(expirationYear.trim(), 10))) {
      errs.expiration_year = 'Expiration year must be a whole number.';
    }
    setFieldErrors((prev) => ({ ...prev, expiration_year: errs.expiration_year ?? '' }));
    return !errs.expiration_year;
  };

  // When a landlord is chosen and no lessor override typed, use the landlord's
  // display name as the lessor.
  useEffect(() => {
    if (landlord?.label && !lessorName.trim()) {
      setLessorName(landlord.label);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [landlord]);

  const addHistoryRow = () => setHistoryRows((rows) => [...rows, newHistoryRow()]);
  const removeHistoryRow = (id: string) =>
    setHistoryRows((rows) => rows.filter((r) => r.id !== id));
  const updateHistoryRow = (id: string, patch: Partial<HistoryRow>) =>
    setHistoryRows((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  // Remember an AI-analysed lease document so it is also uploaded with the lease.
  const queueExtractedFile = (file: File) => {
    setCurrentLeaseFiles((prev) => {
      if (prev.some((qf) => qf.file.name === file.name && qf.file.size === file.size)) {
        return prev;
      }
      return [...prev, { file, id: `ai-${Date.now()}-${Math.random()}` }];
    });
  };

  // Map AI lease-parse suggestions onto the wizard's field state. Mirrors the
  // transforms in LeaseFormPage: money values are stripped to bare numerics,
  // rates come back as decimal fractions (0.03) but the wizard edits percent,
  // and enum-ish values are resolved against their option lists.
  const applyAISuggestions = (suggested: Record<string, unknown>) => {
    const str = (v: unknown): string | undefined =>
      v === null || v === undefined ? undefined : String(v);
    const num = (v: unknown): string | undefined => {
      const s = str(v);
      if (s === undefined) return undefined;
      const cleaned = s.replace(/[^0-9.-]/g, '');
      return cleaned === '' ? undefined : cleaned;
    };
    const pct = (v: unknown): string | undefined => {
      const cleaned = num(v);
      if (cleaned === undefined) return undefined;
      const n = parseFloat(cleaned);
      if (Number.isNaN(n)) return undefined;
      return String(Math.round(n * 100 * 1e6) / 1e6);
    };

    const name = str(suggested.lease_name);
    if (name) setLeaseName(name.slice(0, 255));
    const lessor = str(suggested.lessor_name);
    if (lessor) setLessorName(lessor);
    const expiration = str(suggested.lease_expiration);
    if (expiration) setLeaseExpiration(expiration);
    const notice = str(suggested.notice_period);
    if (notice) setNoticePeriod(notice.slice(0, 255));
    const noticeDays = num(suggested.notice_period_days);
    if (noticeDays !== undefined) setNoticePeriodDays(noticeDays);
    const expYear = num(suggested.expiration_year);
    if (expYear !== undefined) setExpirationYear(expYear);

    const commencement =
      str(suggested.lease_commencement_date) ??
      str(suggested.lease_commencement) ??
      str(suggested.commencement_date);
    if (commencement) setCommencementDate(commencement);

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
    const classificationOption = CLASSIFICATION_OPTIONS.find((o) => o.value === classification);
    if (classificationOption) setLeaseClassification(classificationOption);

    const cur = str(suggested.currency);
    if (cur) {
      const code = cur.trim().toUpperCase();
      if (/^[A-Z]{3}$/.test(code)) setCurrency(code);
    }

    if (typeof suggested.is_short_term_lease === 'boolean') {
      setIsShortTermLease(suggested.is_short_term_lease);
    }
    if (typeof suggested.is_low_value_lease === 'boolean') {
      setIsLowValueLease(suggested.is_low_value_lease);
    }
  };

  const handleCamHistoryParsed = (
    rows: CamHistoryRow[],
    meta: CamHistoryParseResult,
    periodStatus: 'auto' | 'historical',
  ) => {
    setStagedCamRows(rows);
    setStagedCamMeta(meta);
    setStagedCamPeriodStatus(periodStatus);
    setCamReviewVisible(true);
  };

  const handleCamHistoryConfirmed = (
    rows: CamHistoryRow[],
    options: CamHistoryConfirmOptions,
  ) => {
    pendingCamRef.current = { rows, options };
    setCamReviewVisible(false);
  };

  const buildPayload = (): LeaseCreate => {
    const standard = accountingStandard?.value;
    return {
      lease_name: leaseName.trim(),
      office_id: office?.value || undefined,
      manager_id: manager?.value || undefined,
      lessor_name: lessorName.trim() || undefined,
      lease_expiration: leaseExpiration || undefined,
      notice_period: noticePeriod.trim() || undefined,
      notice_period_days: noticePeriodDays ? parseInt(noticePeriodDays, 10) : undefined,
      status: status?.value || undefined,
      expiration_year: parseInt(expirationYear.trim(), 10),
      accounting_standard: standard || undefined,
      lease_classification:
        standard && standard !== 'ifrs16' ? leaseClassification?.value || undefined : undefined,
      lease_commencement_date: commencementDate || undefined,
      payment_amount: paymentAmount ? parseFloat(paymentAmount) : undefined,
      payment_frequency: paymentFrequency?.value || undefined,
      annual_escalation_rate: annualEscalationRate ? parseFloat(annualEscalationRate) / 100 : undefined,
      incremental_borrowing_rate: incrementalBorrowingRate
        ? parseFloat(incrementalBorrowingRate) / 100
        : undefined,
      initial_direct_costs: initialDirectCosts ? parseFloat(initialDirectCosts) : undefined,
      lease_incentives: leaseIncentives ? parseFloat(leaseIncentives) : undefined,
      prepaid_rent: prepaidRent ? parseFloat(prepaidRent) : undefined,
      residual_value_guarantee: residualValueGuarantee ? parseFloat(residualValueGuarantee) : undefined,
      currency: currency.trim() || 'USD',
      is_short_term_lease: isShortTermLease,
      is_low_value_lease: isLowValueLease,
    };
  };

  const handleSubmit = async () => {
    if (!validateTypeAndName()) {
      setActiveStepIndex(0);
      return;
    }
    if (!validateTerm()) {
      setActiveStepIndex(2);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await leasesApi.create(buildPayload());
      const newId = String(res.data.id);
      const warnings: string[] = [];
      let attachmentFailures = 0;

      // Upload documents for the current lease (best-effort).
      for (const qf of currentLeaseFiles) {
        try {
          await attachmentsApi.upload('lease', newId, qf.file);
        } catch {
          attachmentFailures += 1;
        }
      }

      // Link the selected landlord to the office (best-effort) so the
      // relationship set up in the wizard is preserved.
      if (landlord && office) {
        try {
          const fresh = await landlordsApi.get(landlord.value);
          const existingIds = (fresh.data.owned_offices ?? []).map((o) => o.id);
          const officeIds = Array.from(new Set([...existingIds, office.value]));
          await landlordsApi.update(landlord.value, { office_ids: officeIds });
        } catch {
          warnings.push('Landlord could not be linked to the office.');
        }
      }

      // Record prior-term / renewal history. For legacy leases these represent
      // executed history, so mark them executed after creation.
      const rows = historyRows.filter(
        (r) =>
          r.target_expiration ||
          r.new_rent_amount.trim() ||
          r.notes.trim() ||
          r.files.length > 0,
      );
      let historyFailures = 0;
      for (const row of rows) {
        try {
          const created = await leasesApi.createRenewal(newId, {
            target_expiration: row.target_expiration || undefined,
            new_rent_amount: row.new_rent_amount ? parseFloat(row.new_rent_amount) : undefined,
            notes: row.notes.trim() || undefined,
          });
          if (leaseKind === 'legacy') {
            try {
              await leasesApi.updateRenewal(newId, String(created.data.id), { status: 'executed' });
            } catch {
              // Non-critical: history recorded, just not marked executed.
            }
          }
        } catch {
          historyFailures += 1;
        }
        const termLabel = row.target_expiration
          ? `Historical lease term ending ${row.target_expiration}`
          : 'Historical lease document';
        for (const qf of row.files) {
          try {
            await attachmentsApi.upload('lease', newId, qf.file, termLabel);
          } catch {
            attachmentFailures += 1;
          }
        }
      }
      if (historyFailures > 0) {
        warnings.push(`${historyFailures} history entr${historyFailures === 1 ? 'y' : 'ies'} could not be saved.`);
      }
      if (attachmentFailures > 0) {
        warnings.push(`${attachmentFailures} document${attachmentFailures === 1 ? '' : 's'} could not be uploaded.`);
      }

      // Import confirmed historical CAM rows (best-effort).
      const pendingCam = pendingCamRef.current;
      if (pendingCam && pendingCam.rows.length > 0) {
        try {
          await leasesApi.importCamHistory(newId, {
            rows: pendingCam.rows,
            mode: pendingCam.options.mode,
            period_status: pendingCam.options.period_status,
            source: 'ai_import',
            source_document_id: pendingCam.options.source_document_id ?? null,
            allow_active_period_overlap: pendingCam.options.allow_active_period_overlap,
            apply_to_lease: false,
          });
        } catch {
          warnings.push("Historical CAM rows could not be imported — open the lease's CAM schedule to retry.");
        }
        pendingCamRef.current = null;
      }

      if (warnings.length > 0) {
        setError(`Lease created. ${warnings.join(' ')}`);
      }
      navigate(`/leases/${newId}`);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to create lease.');
      setSaving(false);
    }
  };

  const showClassification = accountingStandard?.value && accountingStandard.value !== 'ifrs16';

  const steps = useMemo(
    () => [
      {
        title: 'Lease type',
        description: 'Are you entering a brand-new lease or migrating one with prior history?',
        content: (
          <Container header={<Header variant="h2">Lease type & name</Header>}>
            <SpaceBetween size="l">
              <FormField label="What kind of lease is this?">
                <RadioGroup
                  value={leaseKind}
                  onChange={({ detail }) => setLeaseKind(detail.value as LeaseKind)}
                  items={[
                    {
                      value: 'net_new',
                      label: 'Net-new lease',
                      description: 'A newly signed lease with no prior renewal history.',
                    },
                    {
                      value: 'legacy',
                      label: 'Legacy lease (with prior history)',
                      description:
                        'An existing lease you are migrating in. You can capture prior terms and renewals in a later step.',
                    },
                  ]}
                />
              </FormField>
              <AILeasePrefill
                onSuggested={applyAISuggestions}
                onFileExtracted={queueExtractedFile}
                onHistoryParsed={handleCamHistoryParsed}
              />
              <FormField label="Lease name" constraintText="Required" errorText={fieldErrors.lease_name || undefined}>
                <Input
                  value={leaseName}
                  onChange={({ detail }) => setLeaseName(detail.value)}
                  placeholder="e.g., 123 Main St — Suite 400"
                />
              </FormField>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Property & parties',
        description: 'Link the office, landlord, and manager. Create any that are missing inline.',
        content: (
          <Container header={<Header variant="h2">Property & parties</Header>}>
            <SpaceBetween size="l">
              <FormField label="Office" description="Select an existing office or create a new one inline.">
                <EntityQuickCreateSelect
                  options={officeOptions}
                  selectedOption={office}
                  onChange={setOffice}
                  placeholder="Select office"
                  empty="No offices yet"
                  quickCreate={{
                    label: '+ Add new office…',
                    render: ({ visible, onClose, onCreated }) => (
                      <OfficeQuickCreate visible={visible} onClose={onClose} onCreated={onCreated} />
                    ),
                  }}
                />
              </FormField>
              <FormField
                label="Landlord"
                description="Select or create a landlord. Their name pre-fills the lessor below and they'll be linked to the office."
              >
                <EntityQuickCreateSelect
                  options={landlordOptions}
                  selectedOption={landlord}
                  onChange={setLandlord}
                  placeholder="Select landlord"
                  empty="No landlords yet"
                  quickCreate={{
                    label: '+ Add new landlord…',
                    render: ({ visible, onClose, onCreated }) => (
                      <LandlordQuickCreate visible={visible} onClose={onClose} onCreated={onCreated} />
                    ),
                  }}
                />
              </FormField>
              <FormField label="Lessor name" description="Free-text lessor as it appears on the lease. Override if different from the landlord.">
                <Input
                  value={lessorName}
                  onChange={({ detail }) => setLessorName(detail.value)}
                  placeholder="Lessor / landlord name on the lease"
                />
              </FormField>
              <FormField label="Manager" description="Select an existing manager or create a new one inline.">
                <EntityQuickCreateSelect
                  options={managerOptions}
                  selectedOption={manager}
                  onChange={setManager}
                  placeholder="Select manager"
                  empty="No managers yet"
                  quickCreate={{
                    label: '+ Add new manager…',
                    render: ({ visible, onClose, onCreated }) => (
                      <ManagerQuickCreate visible={visible} onClose={onClose} onCreated={onCreated} />
                    ),
                  }}
                />
              </FormField>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Term & dates',
        description: 'Commencement, expiration, and notice details.',
        content: (
          <Container header={<Header variant="h2">Term & dates</Header>}>
            <SpaceBetween size="l">
              <ColumnLayout columns={2}>
                <FormField label="Commencement date">
                  <DatePicker
                    value={commencementDate}
                    onChange={({ detail }) => setCommencementDate(detail.value)}
                    placeholder="YYYY/MM/DD"
                  />
                </FormField>
                <FormField label="Lease expiration">
                  <DatePicker
                    value={leaseExpiration}
                    onChange={({ detail }) => setLeaseExpiration(detail.value)}
                    placeholder="YYYY/MM/DD"
                  />
                </FormField>
                <FormField label="Expiration year" constraintText="Required" errorText={fieldErrors.expiration_year || undefined}>
                  <Input
                    value={expirationYear}
                    onChange={({ detail }) => setExpirationYear(detail.value)}
                    type="number"
                    inputMode="numeric"
                    placeholder="e.g., 2027"
                  />
                </FormField>
                <FormField label="Status">
                  <Select
                    selectedOption={status}
                    onChange={({ detail }) => setStatus((detail.selectedOption as QuickCreateOption) ?? null)}
                    options={LEASE_STATUS_OPTIONS}
                    placeholder="Select status"
                    empty="No statuses"
                  />
                </FormField>
                <FormField label="Notice period">
                  <Input
                    value={noticePeriod}
                    onChange={({ detail }) => setNoticePeriod(detail.value)}
                    placeholder="e.g., 6 months"
                  />
                </FormField>
                <FormField label="Notice period (days)">
                  <Input
                    value={noticePeriodDays}
                    onChange={({ detail }) => setNoticePeriodDays(detail.value)}
                    type="number"
                    inputMode="numeric"
                    placeholder="e.g., 180"
                  />
                </FormField>
              </ColumnLayout>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Financials',
        description: 'Rent, escalation, and accounting terms.',
        isOptional: true,
        content: (
          <Container header={<Header variant="h2">Financial & accounting terms</Header>}>
            <SpaceBetween size="l">
              <ColumnLayout columns={2}>
                <FormField label="Payment amount">
                  <Input value={paymentAmount} onChange={({ detail }) => setPaymentAmount(detail.value)} type="number" placeholder="e.g., 12500" />
                </FormField>
                <FormField label="Payment frequency">
                  <Select
                    selectedOption={paymentFrequency}
                    onChange={({ detail }) => setPaymentFrequency((detail.selectedOption as QuickCreateOption) ?? null)}
                    options={FREQUENCY_OPTIONS}
                    placeholder="Select frequency"
                  />
                </FormField>
                <FormField label="Annual escalation rate (%)">
                  <Input value={annualEscalationRate} onChange={({ detail }) => setAnnualEscalationRate(detail.value)} type="number" placeholder="e.g., 3" />
                </FormField>
                <FormField label="Currency">
                  <Input value={currency} onChange={({ detail }) => setCurrency(detail.value)} placeholder="USD" />
                </FormField>
              </ColumnLayout>
              <ColumnLayout columns={2}>
                <FormField label="Accounting standard">
                  <Select
                    selectedOption={accountingStandard}
                    onChange={({ detail }) => setAccountingStandard((detail.selectedOption as QuickCreateOption) ?? null)}
                    options={ACCOUNTING_STD_OPTIONS}
                    placeholder="None (no accounting recognition)"
                    filteringType="auto"
                  />
                </FormField>
                {showClassification && (
                  <FormField label="Lease classification">
                    <Select
                      selectedOption={leaseClassification}
                      onChange={({ detail }) => setLeaseClassification((detail.selectedOption as QuickCreateOption) ?? null)}
                      options={CLASSIFICATION_OPTIONS}
                      placeholder="Select classification"
                    />
                  </FormField>
                )}
                <FormField label="Incremental borrowing rate (%)">
                  <Input value={incrementalBorrowingRate} onChange={({ detail }) => setIncrementalBorrowingRate(detail.value)} type="number" placeholder="e.g., 4.5" />
                </FormField>
                <FormField label="Initial direct costs">
                  <Input value={initialDirectCosts} onChange={({ detail }) => setInitialDirectCosts(detail.value)} type="number" placeholder="e.g., 5000" />
                </FormField>
                <FormField label="Lease incentives">
                  <Input value={leaseIncentives} onChange={({ detail }) => setLeaseIncentives(detail.value)} type="number" placeholder="e.g., 2000" />
                </FormField>
                <FormField label="Prepaid rent">
                  <Input value={prepaidRent} onChange={({ detail }) => setPrepaidRent(detail.value)} type="number" placeholder="e.g., 12500" />
                </FormField>
                <FormField label="Residual value guarantee">
                  <Input value={residualValueGuarantee} onChange={({ detail }) => setResidualValueGuarantee(detail.value)} type="number" placeholder="e.g., 0" />
                </FormField>
              </ColumnLayout>
              <SpaceBetween size="s">
                <Checkbox checked={isShortTermLease} onChange={({ detail }) => setIsShortTermLease(detail.checked)}>
                  Short-term lease (≤ 12 months) — practical expedient
                </Checkbox>
                <Checkbox checked={isLowValueLease} onChange={({ detail }) => setIsLowValueLease(detail.checked)}>
                  Low-value asset lease — practical expedient
                </Checkbox>
              </SpaceBetween>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: leaseKind === 'legacy' ? 'Prior history' : 'Renewals',
        description:
          leaseKind === 'legacy'
            ? 'Capture prior terms and renewals for this migrated lease.'
            : 'Optionally record planned or executed renewals.',
        isOptional: true,
        content: (
          <Container
            header={
              <Header
                variant="h2"
                actions={<Button iconName="add-plus" onClick={addHistoryRow}>Add entry</Button>}
                description={
                  leaseKind === 'legacy'
                    ? 'Each entry is recorded against the lease and marked as executed history.'
                    : 'Each entry is recorded as a renewal in progress.'
                }
              >
                {leaseKind === 'legacy' ? 'Prior terms & renewals' : 'Renewals'}
              </Header>
            }
          >
            <SpaceBetween size="l">
              {historyRows.length === 0 && (
                <Box color="text-status-inactive">No entries yet. Use “Add entry” to record history.</Box>
              )}
              {historyRows.map((row, idx) => (
                <Container
                  key={row.id}
                  header={
                    <Header
                      variant="h3"
                      actions={<Button iconName="remove" variant="icon" onClick={() => removeHistoryRow(row.id)} ariaLabel="Remove entry" />}
                    >
                      Entry {idx + 1}
                    </Header>
                  }
                >
                  <ColumnLayout columns={2}>
                    <FormField label="Term expiration">
                      <DatePicker
                        value={row.target_expiration}
                        onChange={({ detail }) => updateHistoryRow(row.id, { target_expiration: detail.value })}
                        placeholder="YYYY/MM/DD"
                      />
                    </FormField>
                    <FormField label="Rent amount">
                      <Input
                        value={row.new_rent_amount}
                        onChange={({ detail }) => updateHistoryRow(row.id, { new_rent_amount: detail.value })}
                        type="number"
                        placeholder="e.g., 11000"
                      />
                    </FormField>
                  </ColumnLayout>
                  <FormField label="Notes">
                    <Textarea
                      value={row.notes}
                      onChange={({ detail }) => updateHistoryRow(row.id, { notes: detail.value })}
                      placeholder="Optional details about this term"
                    />
                  </FormField>
                  <FileQueueField
                    files={row.files}
                    onChange={(files) => updateHistoryRow(row.id, { files })}
                    disabled={saving}
                  />
                </Container>
              ))}
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Documents',
        description: 'Attach the current lease agreement and any supporting files (optional).',
        isOptional: true,
        content: (
          <Container header={<Header variant="h2">Current lease documents</Header>}>
            <SpaceBetween size="l">
              <Box variant="p" color="text-body-secondary">
                Upload the executed lease agreement and any supporting documents for the
                current term. Historical lease documents can be attached to each entry in
                the previous step. All files are uploaded after the lease is created.
              </Box>
              <FileQueueField
                files={currentLeaseFiles}
                onChange={setCurrentLeaseFiles}
                disabled={saving}
              />
            </SpaceBetween>
          </Container>
        ),
      },      {
        title: 'Review & create',
        description: 'Confirm the details before creating the lease.',
        content: (
          <Container header={<Header variant="h2">Review</Header>}>
            <SpaceBetween size="l">
              {error && <Alert type="error">{error}</Alert>}
              <ColumnLayout columns={2} variant="text-grid">
                <div>
                  <Box variant="awsui-key-label">Lease type</Box>
                  <div>{leaseKind === 'legacy' ? 'Legacy (with history)' : 'Net-new'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Lease name</Box>
                  <div>{leaseName || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Office</Box>
                  <div>{office?.label || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Landlord / lessor</Box>
                  <div>{lessorName || landlord?.label || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Manager</Box>
                  <div>{manager?.label || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Expiration year</Box>
                  <div>{expirationYear || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Payment</Box>
                  <div>{paymentAmount ? `${paymentAmount} ${currency} ${paymentFrequency?.label ?? ''}`.trim() : '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">History entries</Box>
                  <div>{historyRows.filter((r) => r.target_expiration || r.new_rent_amount.trim() || r.notes.trim()).length}</div>
                </div>
              </ColumnLayout>
            </SpaceBetween>
          </Container>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      leaseKind, leaseName, fieldErrors, officeOptions, office, landlordOptions, landlord, lessorName,
      managerOptions, manager, commencementDate, leaseExpiration, expirationYear, status, noticePeriod,
      noticePeriodDays, paymentAmount, paymentFrequency, annualEscalationRate, currency, accountingStandard,
      leaseClassification, showClassification, incrementalBorrowingRate, initialDirectCosts, leaseIncentives,
      prepaidRent, residualValueGuarantee, isShortTermLease, isLowValueLease, historyRows, error,
      currentLeaseFiles, saving,
    ],
  );

  return (
    <>
      <CamHistoryReviewModal
        visible={camReviewVisible}
        rows={stagedCamRows}
        warnings={stagedCamMeta?.warnings}
        defaultPeriodStatus={stagedCamPeriodStatus}
        source="ai_import"
        onDismiss={() => setCamReviewVisible(false)}
        onConfirm={handleCamHistoryConfirmed}
      />
      <ContentLayout
        header={
          <SpaceBetween size="m">
            <BreadcrumbGroup
              items={[
                { text: 'Leases', href: '/leases' },
                { text: 'New lease wizard', href: '#' },
              ]}
              onFollow={(e) => {
                e.preventDefault();
                if (e.detail.href === '/leases') navigate('/leases');
              }}
            />
            <Header
              variant="h1"
              description="A guided walkthrough to enter a new or legacy lease and link all related records."
            >
              New lease wizard
            </Header>
          </SpaceBetween>
        }
      >
        <Wizard
          steps={steps}
          activeStepIndex={activeStepIndex}
          i18nStrings={wizardI18nStrings('Create lease')}
          isLoadingNextStep={saving}
          onNavigate={({ detail }) => {
            if (activeStepIndex === 0 && detail.requestedStepIndex > 0 && !validateTypeAndName()) {
              return;
            }
            if (activeStepIndex === 2 && detail.requestedStepIndex > 2 && !validateTerm()) {
              return;
            }
            setActiveStepIndex(detail.requestedStepIndex);
          }}
          onCancel={() => navigate('/leases')}
          onSubmit={handleSubmit}
        />
      </ContentLayout>
    </>
  );
};

export default LeaseWizardPage;
