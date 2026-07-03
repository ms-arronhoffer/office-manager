import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Multiselect from '@cloudscape-design/components/multiselect';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { leasing, leaseTemplates, leasingFunnel } from '@/api';
import type {
  ResidentLease,
  ResidentLeaseStatus,
  ResidentLeaseType,
  RentalUnit,
  Resident,
  LeaseTemplate,
} from '@/types';

const fmtMoney = (v: string | null) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const LEASE_STATUSES: ResidentLeaseStatus[] = [
  'draft',
  'pending',
  'active',
  'ended',
  'terminated',
];

const LEASE_TYPES: ResidentLeaseType[] = [
  'fixed_term',
  'month_to_month',
  'at_will',
  'short_term',
];

const leaseBadge = (s: ResidentLeaseStatus) => {
  const color =
    s === 'active' ? 'green' : s === 'pending' || s === 'draft' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

interface Opt { label: string; value: string; }

const ResidentLeasesPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [leases, setLeases] = useState<ResidentLease[]>([]);
  const [units, setUnits] = useState<RentalUnit[]>([]);
  const [residents, setResidents] = useState<Resident[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<Opt>({ label: 'All statuses', value: '' });

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ResidentLease | null>(null);
  const [unitId, setUnitId] = useState('');
  const [name, setName] = useState('');
  const [statusValue, setStatusValue] = useState<ResidentLeaseStatus>('draft');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [rentAmount, setRentAmount] = useState('');
  const [deposit, setDeposit] = useState('');
  const [leaseType, setLeaseType] = useState<ResidentLeaseType | ''>('');
  const [escalationRate, setEscalationRate] = useState('');
  const [lateFeeAmount, setLateFeeAmount] = useState('');
  const [lateFeeGraceDays, setLateFeeGraceDays] = useState('');
  const [noticePeriodDays, setNoticePeriodDays] = useState('');
  const [petDeposit, setPetDeposit] = useState('');
  const [renewalOption, setRenewalOption] = useState(false);
  const [occupantIds, setOccupantIds] = useState<readonly Opt[]>([]);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

  // E-sign modal state
  const [esignOpen, setEsignOpen] = useState(false);
  const [esignLease, setEsignLease] = useState<ResidentLease | null>(null);
  const [templates, setTemplates] = useState<LeaseTemplate[]>([]);
  const [templateId, setTemplateId] = useState('');
  const [esignTitle, setEsignTitle] = useState('');
  const [esignSending, setEsignSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = statusFilter.value ? { status: statusFilter.value } : undefined;
      const [l, u, r] = await Promise.all([
        leasing.listLeases(params),
        leasing.listUnits(),
        leasing.listResidents(),
      ]);
      setLeases(l.data);
      setUnits(u.data);
      setResidents(r.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load leases.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash, statusFilter.value]);

  useEffect(() => {
    load();
  }, [load]);

  const unitLabel = useCallback(
    (id: string) => {
      const u = units.find((x) => x.id === id);
      return u ? u.unit_number + (u.name ? ` · ${u.name}` : '') : id;
    },
    [units],
  );

  const unitOptions: Opt[] = useMemo(
    () => units.map((u) => ({ label: unitLabel(u.id), value: u.id })),
    [units, unitLabel],
  );

  const residentOptions: Opt[] = useMemo(
    () =>
      residents.map((r) => ({
        label: `${r.first_name} ${r.last_name}`,
        value: r.id,
      })),
    [residents],
  );

  const openCreate = () => {
    setEditing(null);
    setUnitId('');
    setName('');
    setStatusValue('draft');
    setStartDate('');
    setEndDate('');
    setRentAmount('');
    setDeposit('');
    setLeaseType('');
    setEscalationRate('');
    setLateFeeAmount('');
    setLateFeeGraceDays('');
    setNoticePeriodDays('');
    setPetDeposit('');
    setRenewalOption(false);
    setOccupantIds([]);
    setNotes('');
    setModalOpen(true);
  };

  const openEdit = (l: ResidentLease) => {
    setEditing(l);
    setUnitId(l.unit_id);
    setName(l.name ?? '');
    setStatusValue(l.status);
    setStartDate(l.start_date ?? '');
    setEndDate(l.end_date ?? '');
    setRentAmount(l.rent_amount ?? '');
    setDeposit(l.security_deposit ?? '');
    setLeaseType(l.lease_type ?? '');
    setEscalationRate(l.rent_escalation_rate ?? '');
    setLateFeeAmount(l.late_fee_amount ?? '');
    setLateFeeGraceDays(l.late_fee_grace_days != null ? String(l.late_fee_grace_days) : '');
    setNoticePeriodDays(l.notice_period_days != null ? String(l.notice_period_days) : '');
    setPetDeposit(l.pet_deposit ?? '');
    setRenewalOption(l.renewal_option);
    setOccupantIds(
      l.occupants.map((o) => ({
        label:
          o.resident != null
            ? `${o.resident.first_name} ${o.resident.last_name}`
            : o.resident_id,
        value: o.resident_id,
      })),
    );
    setNotes(l.notes ?? '');
    setModalOpen(true);
  };

  const save = async () => {
    if (!editing && !unitId) {
      addFlash({ type: 'error', content: 'A unit is required.' });
      return;
    }
    setSaving(true);
    try {
      const occupants = occupantIds.map((o, i) => ({
        resident_id: o.value,
        is_primary: i === 0,
      }));
      const common = {
        name: name.trim() || null,
        status: statusValue,
        start_date: startDate || null,
        end_date: endDate || null,
        rent_amount: rentAmount.trim() || null,
        security_deposit: deposit.trim() || null,
        lease_type: leaseType || null,
        rent_escalation_rate: escalationRate.trim() || null,
        late_fee_amount: lateFeeAmount.trim() || null,
        late_fee_grace_days: lateFeeGraceDays ? Number(lateFeeGraceDays) : null,
        notice_period_days: noticePeriodDays ? Number(noticePeriodDays) : null,
        pet_deposit: petDeposit.trim() || null,
        renewal_option: renewalOption,
        notes: notes.trim() || null,
        occupants,
      };
      if (editing) {
        await leasing.updateLease(editing.id, common);
        addFlash({ type: 'success', content: 'Lease updated.' });
      } else {
        await leasing.createLease({ unit_id: unitId, ...common });
        addFlash({ type: 'success', content: 'Lease created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save lease.' });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (l: ResidentLease) => {
    if (!window.confirm('Delete this lease?')) return;
    try {
      await leasing.deleteLease(l.id);
      addFlash({ type: 'success', content: 'Lease deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete lease.' });
    }
  };

  const openEsign = async (l: ResidentLease) => {
    setEsignLease(l);
    setTemplateId('');
    setEsignTitle('');
    setEsignOpen(true);
    try {
      const r = await leaseTemplates.list({ active_only: true });
      setTemplates(r.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load lease templates.' });
    }
  };

  const sendEsign = async () => {
    if (!esignLease) return;
    if (!templateId) {
      addFlash({ type: 'error', content: 'Select a lease template.' });
      return;
    }
    setEsignSending(true);
    try {
      await leasingFunnel.createSignatureFromTemplate({
        resident_lease_id: esignLease.id,
        template_id: templateId,
        title: esignTitle.trim() || null,
      });
      addFlash({ type: 'success', content: 'Lease sent for e-signature.' });
      setEsignOpen(false);
    } catch {
      addFlash({
        type: 'error',
        content: 'Failed to send for e-signature. Ensure occupants have email addresses.',
      });
    } finally {
      setEsignSending(false);
    }
  };

  const templateOptions: Opt[] = useMemo(
    () => templates.map((t) => ({ label: t.name + (t.is_default ? ' (default)' : ''), value: t.id })),
    [templates],
  );

  return (
    <SpaceBetween size="l">
      <Table<ResidentLease>
        loading={loading}
        items={leases}
        variant="container"
        header={
          <Header
            counter={`(${leases.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Select
                  selectedOption={statusFilter}
                  onChange={({ detail }) => setStatusFilter(detail.selectedOption as Opt)}
                  options={[
                    { label: 'All statuses', value: '' },
                    ...LEASE_STATUSES.map((s) => ({ label: s, value: s })),
                  ]}
                />
                <Button variant="primary" onClick={openCreate}>
                  Add lease
                </Button>
              </SpaceBetween>
            }
          >
            Resident leases
          </Header>
        }
        columnDefinitions={[
          { id: 'unit', header: 'Unit', cell: (l) => unitLabel(l.unit_id) },
          {
            id: 'occupants',
            header: 'Occupants',
            cell: (l) =>
              l.occupants.length > 0
                ? l.occupants
                    .map((o) =>
                      o.resident
                        ? `${o.resident.first_name} ${o.resident.last_name}`
                        : o.resident_id,
                    )
                    .join(', ')
                : '—',
          },
          { id: 'rent', header: 'Rent', cell: (l) => fmtMoney(l.rent_amount) },
          { id: 'start', header: 'Start', cell: (l) => l.start_date ?? '—' },
          { id: 'end', header: 'End', cell: (l) => l.end_date ?? '—' },
          { id: 'status', header: 'Status', cell: (l) => leaseBadge(l.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (l) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => openEdit(l)}>
                  Edit
                </Button>
                <Button variant="inline-link" onClick={() => openEsign(l)}>
                  Send for e-sign
                </Button>
                <Button variant="inline-link" onClick={() => remove(l)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No leases yet.</Box>}
      />

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editing ? 'Edit lease' : 'Add lease'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={saving} onClick={save}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Unit">
            <Select
              disabled={!!editing}
              selectedOption={unitOptions.find((o) => o.value === unitId) ?? null}
              onChange={({ detail }) => setUnitId(detail.selectedOption.value ?? '')}
              options={unitOptions}
              filteringType="auto"
              placeholder="Select a unit"
            />
          </FormField>
          <FormField label="Occupants (first is primary)">
            <Multiselect
              selectedOptions={occupantIds}
              onChange={({ detail }) => setOccupantIds(detail.selectedOptions as Opt[])}
              options={residentOptions}
              filteringType="auto"
              placeholder="Select residents"
            />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Lease name">
              <Input value={name} onChange={({ detail }) => setName(detail.value)} />
            </FormField>
            <FormField label="Status">
              <Select
                selectedOption={{ label: statusValue, value: statusValue }}
                onChange={({ detail }) =>
                  setStatusValue(detail.selectedOption.value as ResidentLeaseStatus)
                }
                options={LEASE_STATUSES.map((s) => ({ label: s, value: s }))}
              />
            </FormField>
            <FormField label="Start date">
              <Input
                type="date"
                value={startDate}
                onChange={({ detail }) => setStartDate(detail.value)}
              />
            </FormField>
            <FormField label="End date">
              <Input
                type="date"
                value={endDate}
                onChange={({ detail }) => setEndDate(detail.value)}
              />
            </FormField>
            <FormField label="Rent amount">
              <Input
                type="number"
                value={rentAmount}
                onChange={({ detail }) => setRentAmount(detail.value)}
              />
            </FormField>
            <FormField label="Security deposit">
              <Input
                type="number"
                value={deposit}
                onChange={({ detail }) => setDeposit(detail.value)}
              />
            </FormField>
            <FormField label="Lease type">
              <Select
                selectedOption={
                  leaseType ? { label: leaseType, value: leaseType } : null
                }
                onChange={({ detail }) =>
                  setLeaseType(detail.selectedOption.value as ResidentLeaseType)
                }
                options={LEASE_TYPES.map((t) => ({ label: t, value: t }))}
                placeholder="Select a lease type"
              />
            </FormField>
            <FormField label="Rent escalation rate (%)">
              <Input
                type="number"
                value={escalationRate}
                onChange={({ detail }) => setEscalationRate(detail.value)}
              />
            </FormField>
            <FormField label="Pet deposit">
              <Input
                type="number"
                value={petDeposit}
                onChange={({ detail }) => setPetDeposit(detail.value)}
              />
            </FormField>
            <FormField label="Late fee amount">
              <Input
                type="number"
                value={lateFeeAmount}
                onChange={({ detail }) => setLateFeeAmount(detail.value)}
              />
            </FormField>
            <FormField label="Late fee grace (days)">
              <Input
                type="number"
                value={lateFeeGraceDays}
                onChange={({ detail }) => setLateFeeGraceDays(detail.value)}
              />
            </FormField>
            <FormField label="Notice period (days)">
              <Input
                type="number"
                value={noticePeriodDays}
                onChange={({ detail }) => setNoticePeriodDays(detail.value)}
              />
            </FormField>
            <FormField label="Renewal option">
              <Select
                selectedOption={
                  renewalOption
                    ? { label: 'Yes', value: 'yes' }
                    : { label: 'No', value: 'no' }
                }
                onChange={({ detail }) =>
                  setRenewalOption(detail.selectedOption.value === 'yes')
                }
                options={[
                  { label: 'No', value: 'no' },
                  { label: 'Yes', value: 'yes' },
                ]}
              />
            </FormField>
          </ColumnLayout>
          <FormField label="Notes">
            <Textarea value={notes} onChange={({ detail }) => setNotes(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={esignOpen}
        onDismiss={() => setEsignOpen(false)}
        header="Send lease for e-signature"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setEsignOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={esignSending} onClick={sendEsign}>
                Send
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box variant="p">
            A signature request is generated from the selected template and sent to every
            occupant on this lease that has an email address.
          </Box>
          <FormField label="Lease template">
            <Select
              selectedOption={templateOptions.find((o) => o.value === templateId) ?? null}
              onChange={({ detail }) => setTemplateId(detail.selectedOption.value ?? '')}
              options={templateOptions}
              filteringType="auto"
              placeholder="Select a template"
              empty="No active templates"
            />
          </FormField>
          <FormField label="Title (optional)">
            <Input
              value={esignTitle}
              onChange={({ detail }) => setEsignTitle(detail.value)}
              placeholder="Defaults to the template name"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default ResidentLeasesPage;
