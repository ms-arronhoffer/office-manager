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
} from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import type { LeaseCreate, Office, Manager } from '@/types';

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
  quarem_date: string;
  quarem_status: string;
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
  quarem_date: '',
  quarem_status: '',
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
          quarem_date: l.quarem_date || '',
          quarem_status: l.quarem_status || '',
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
        quarem_date: form.quarem_date || undefined,
        quarem_status: form.quarem_status.trim() || undefined,
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
        const res = await leasesApi.create(payload);
        const newId = String(res.data.id);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('lease', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        if (failed.length > 0) {
          setError(
            `Lease created, but ${failed.length} attachment(s) failed: ${failed.join(', ')}. Re-upload from the lease page.`,
          );
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
                <Select
                  selectedOption={selectedOffice}
                  onChange={({ detail }) =>
                    setSelectedOffice(detail.selectedOption as SelectOption)
                  }
                  options={officeOptions}
                  placeholder="Select office"
                  filteringType="auto"
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
              <FormField label="Quarem Date">
                <DatePicker
                  value={form.quarem_date || ''}
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, quarem_date: detail.value }))
                  }
                  placeholder="YYYY/MM/DD"
                  openCalendarAriaLabel={(selectedDate) =>
                    'Choose Quarem date' +
                    (selectedDate ? `, selected date is ${selectedDate}` : '')
                  }
                />
              </FormField>
              <FormField label="Quarem Status">
                <Input
                  value={form.quarem_status}
                  onChange={({ detail }) =>
                    setForm((f) => ({ ...f, quarem_status: detail.value }))
                  }
                  placeholder="e.g., Pending"
                />
              </FormField>
            </SpaceBetween>

            <FormField label="Manager">
              <Select
                selectedOption={selectedManager}
                onChange={({ detail }) =>
                  setSelectedManager(detail.selectedOption as SelectOption)
                }
                options={managerOptions}
                placeholder="Select manager"
                filteringType="auto"
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
