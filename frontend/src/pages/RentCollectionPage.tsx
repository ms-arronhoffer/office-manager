import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { rent, leasing } from '@/api';
import type { RentCharge, SecurityDeposit, ResidentLease } from '@/types';

const fmtMoney = (v: string | null) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const today = () => new Date().toISOString().slice(0, 10);
const firstOfMonth = () => `${new Date().toISOString().slice(0, 7)}-01`;

const CHARGE_TYPES = ['rent', 'utility', 'parking', 'pet', 'other'];
const FREQUENCIES = ['monthly', 'weekly', 'once'];
const LATE_FEE_TYPES = ['none', 'flat', 'percent'];

interface Opt { label: string; value: string; }

const depositBadge = (s: string) => {
  const color = s === 'held' ? 'blue' : s === 'returned' ? 'green' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

const RentCollectionPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [charges, setCharges] = useState<RentCharge[]>([]);
  const [deposits, setDeposits] = useState<SecurityDeposit[]>([]);
  const [leases, setLeases] = useState<ResidentLease[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  // Charge modal
  const [chargeOpen, setChargeOpen] = useState(false);
  const [editing, setEditing] = useState<RentCharge | null>(null);
  const [leaseId, setLeaseId] = useState('');
  const [chargeType, setChargeType] = useState('rent');
  const [amount, setAmount] = useState('');
  const [frequency, setFrequency] = useState('monthly');
  const [dayOfMonth, setDayOfMonth] = useState('1');
  const [graceDays, setGraceDays] = useState('0');
  const [lateFeeType, setLateFeeType] = useState('none');
  const [lateFeeAmount, setLateFeeAmount] = useState('');
  const [description, setDescription] = useState('');
  const [savingCharge, setSavingCharge] = useState(false);

  // Deposit modal
  const [depositOpen, setDepositOpen] = useState(false);
  const [depLeaseId, setDepLeaseId] = useState('');
  const [depAmount, setDepAmount] = useState('');
  const [depNotes, setDepNotes] = useState('');
  const [savingDeposit, setSavingDeposit] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, d, l] = await Promise.all([
        rent.listCharges(),
        rent.listDeposits(),
        leasing.listLeases(),
      ]);
      setCharges(c.data);
      setDeposits(d.data);
      setLeases(l.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load rent data.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const leaseLabel = useCallback(
    (id: string) => {
      const l = leases.find((x) => x.id === id);
      if (!l) return id;
      const who = l.occupants
        .map((o) => (o.resident ? `${o.resident.first_name} ${o.resident.last_name}` : ''))
        .filter(Boolean)
        .join(', ');
      return l.name || who || id;
    },
    [leases],
  );

  const leaseOptions: Opt[] = useMemo(
    () => leases.map((l) => ({ label: leaseLabel(l.id), value: l.id })),
    [leases, leaseLabel],
  );

  const runBilling = async () => {
    setRunning(true);
    try {
      const r = await rent.runBilling();
      addFlash({ type: 'success', content: `Billing run generated ${r.data.generated} invoice(s).` });
    } catch {
      addFlash({ type: 'error', content: 'Billing run failed.' });
    } finally {
      setRunning(false);
    }
  };

  const applyLateFees = async () => {
    setRunning(true);
    try {
      const r = await rent.applyLateFees();
      addFlash({ type: 'success', content: `Assessed ${r.data.assessed} late fee(s).` });
    } catch {
      addFlash({ type: 'error', content: 'Late fee run failed.' });
    } finally {
      setRunning(false);
    }
  };

  const openChargeCreate = () => {
    setEditing(null);
    setLeaseId('');
    setChargeType('rent');
    setAmount('');
    setFrequency('monthly');
    setDayOfMonth('1');
    setGraceDays('0');
    setLateFeeType('none');
    setLateFeeAmount('');
    setDescription('');
    setChargeOpen(true);
  };

  const openChargeEdit = (c: RentCharge) => {
    setEditing(c);
    setLeaseId(c.resident_lease_id);
    setChargeType(c.charge_type);
    setAmount(c.amount);
    setFrequency(c.frequency);
    setDayOfMonth(String(c.day_of_month));
    setGraceDays(String(c.grace_days));
    setLateFeeType(c.late_fee_type);
    setLateFeeAmount(c.late_fee_amount ?? '');
    setDescription(c.description ?? '');
    setChargeOpen(true);
  };

  const saveCharge = async () => {
    if (!editing && !leaseId) {
      addFlash({ type: 'error', content: 'A lease is required.' });
      return;
    }
    if (!amount.trim()) {
      addFlash({ type: 'error', content: 'Amount is required.' });
      return;
    }
    setSavingCharge(true);
    try {
      const common = {
        charge_type: chargeType,
        amount: amount.trim(),
        frequency,
        day_of_month: Number(dayOfMonth) || 1,
        grace_days: Number(graceDays) || 0,
        late_fee_type: lateFeeType,
        late_fee_amount: lateFeeType === 'none' ? null : lateFeeAmount.trim() || null,
        description: description.trim() || null,
      };
      if (editing) {
        await rent.updateCharge(editing.id, common);
        addFlash({ type: 'success', content: 'Charge updated.' });
      } else {
        await rent.createCharge({ resident_lease_id: leaseId, ...common });
        addFlash({ type: 'success', content: 'Charge created.' });
      }
      setChargeOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save charge.' });
    } finally {
      setSavingCharge(false);
    }
  };

  const generateInvoice = async (c: RentCharge) => {
    try {
      const r = await rent.generateInvoice(c.id, firstOfMonth());
      addFlash({
        type: 'success',
        content: `Generated ${r.data.generated} invoice(s) for this charge.`,
      });
    } catch {
      addFlash({ type: 'error', content: 'Failed to generate invoice.' });
    }
  };

  const removeCharge = async (c: RentCharge) => {
    if (!window.confirm('Delete this charge?')) return;
    try {
      await rent.deleteCharge(c.id);
      addFlash({ type: 'success', content: 'Charge deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete charge.' });
    }
  };

  const openDeposit = () => {
    setDepLeaseId('');
    setDepAmount('');
    setDepNotes('');
    setDepositOpen(true);
  };

  const saveDeposit = async () => {
    if (!depLeaseId || !depAmount.trim()) {
      addFlash({ type: 'error', content: 'Lease and amount are required.' });
      return;
    }
    setSavingDeposit(true);
    try {
      await rent.createDeposit({
        resident_lease_id: depLeaseId,
        amount: depAmount.trim(),
        held_date: today(),
        notes: depNotes.trim() || null,
      });
      addFlash({ type: 'success', content: 'Deposit recorded.' });
      setDepositOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to record deposit.' });
    } finally {
      setSavingDeposit(false);
    }
  };

  const returnDeposit = async (d: SecurityDeposit) => {
    const raw = window.prompt('Amount to return to resident?', d.amount);
    if (raw == null) return;
    const returned = Number(raw.trim());
    if (!Number.isFinite(returned) || returned < 0) {
      addFlash({ type: 'error', content: 'Enter a valid non-negative amount.' });
      return;
    }
    const held = Number(d.amount);
    const forfeited = Number.isFinite(held) ? Math.max(0, held - returned) : 0;
    try {
      await rent.returnDeposit(d.id, {
        returned_amount: String(returned),
        forfeited_amount: String(forfeited),
        returned_date: today(),
      });
      addFlash({ type: 'success', content: 'Deposit returned.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to return deposit.' });
    }
  };

  return (
    <SpaceBetween size="l">
      <Container
        header={
          <Header
            variant="h3"
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button loading={running} onClick={runBilling}>
                  Run billing
                </Button>
                <Button loading={running} onClick={applyLateFees}>
                  Apply late fees
                </Button>
              </SpaceBetween>
            }
          >
            Billing actions
          </Header>
        }
      >
        <Box variant="p">
          Run recurring billing to generate invoices for active rent charges, or apply late
          fees to overdue invoices.
        </Box>
      </Container>

      <Table<RentCharge>
        loading={loading}
        items={charges}
        variant="container"
        header={
          <Header
            counter={`(${charges.length})`}
            actions={
              <Button variant="primary" onClick={openChargeCreate}>
                Add charge
              </Button>
            }
          >
            Recurring charges
          </Header>
        }
        columnDefinitions={[
          { id: 'lease', header: 'Lease', cell: (c) => leaseLabel(c.resident_lease_id) },
          { id: 'type', header: 'Type', cell: (c) => c.charge_type },
          { id: 'amount', header: 'Amount', cell: (c) => fmtMoney(c.amount) },
          { id: 'freq', header: 'Frequency', cell: (c) => c.frequency },
          { id: 'day', header: 'Day', cell: (c) => c.day_of_month },
          {
            id: 'active',
            header: 'Active',
            cell: (c) => (c.active ? <Badge color="green">active</Badge> : <Badge color="grey">inactive</Badge>),
          },
          {
            id: 'actions',
            header: 'Actions',
            cell: (c) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => generateInvoice(c)}>
                  Invoice now
                </Button>
                <Button variant="inline-link" onClick={() => openChargeEdit(c)}>
                  Edit
                </Button>
                <Button variant="inline-link" onClick={() => removeCharge(c)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No recurring charges yet.</Box>}
      />

      <Table<SecurityDeposit>
        loading={loading}
        items={deposits}
        variant="container"
        header={
          <Header
            counter={`(${deposits.length})`}
            actions={
              <Button variant="primary" onClick={openDeposit}>
                Record deposit
              </Button>
            }
          >
            Security deposits
          </Header>
        }
        columnDefinitions={[
          { id: 'lease', header: 'Lease', cell: (d) => leaseLabel(d.resident_lease_id) },
          { id: 'amount', header: 'Amount', cell: (d) => fmtMoney(d.amount) },
          { id: 'held', header: 'Held date', cell: (d) => d.held_date },
          { id: 'returned', header: 'Returned', cell: (d) => fmtMoney(d.returned_amount) },
          { id: 'status', header: 'Status', cell: (d) => depositBadge(d.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (d) =>
              d.status === 'held' ? (
                <Button variant="inline-link" onClick={() => returnDeposit(d)}>
                  Return
                </Button>
              ) : (
                '—'
              ),
          },
        ]}
        empty={<Box textAlign="center">No deposits recorded.</Box>}
      />

      <Modal
        visible={chargeOpen}
        onDismiss={() => setChargeOpen(false)}
        header={editing ? 'Edit charge' : 'Add charge'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setChargeOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={savingCharge} onClick={saveCharge}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Lease">
            <Select
              disabled={!!editing}
              selectedOption={leaseOptions.find((o) => o.value === leaseId) ?? null}
              onChange={({ detail }) => setLeaseId(detail.selectedOption.value ?? '')}
              options={leaseOptions}
              filteringType="auto"
              placeholder="Select a lease"
            />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Charge type">
              <Select
                selectedOption={{ label: chargeType, value: chargeType }}
                onChange={({ detail }) => setChargeType(detail.selectedOption.value ?? 'rent')}
                options={CHARGE_TYPES.map((t) => ({ label: t, value: t }))}
              />
            </FormField>
            <FormField label="Amount">
              <Input type="number" value={amount} onChange={({ detail }) => setAmount(detail.value)} />
            </FormField>
            <FormField label="Frequency">
              <Select
                selectedOption={{ label: frequency, value: frequency }}
                onChange={({ detail }) => setFrequency(detail.selectedOption.value ?? 'monthly')}
                options={FREQUENCIES.map((f) => ({ label: f, value: f }))}
              />
            </FormField>
            <FormField label="Day of month">
              <Input
                type="number"
                value={dayOfMonth}
                onChange={({ detail }) => setDayOfMonth(detail.value)}
              />
            </FormField>
            <FormField label="Grace days">
              <Input
                type="number"
                value={graceDays}
                onChange={({ detail }) => setGraceDays(detail.value)}
              />
            </FormField>
            <FormField label="Late fee type">
              <Select
                selectedOption={{ label: lateFeeType, value: lateFeeType }}
                onChange={({ detail }) => setLateFeeType(detail.selectedOption.value ?? 'none')}
                options={LATE_FEE_TYPES.map((t) => ({ label: t, value: t }))}
              />
            </FormField>
            {lateFeeType !== 'none' && (
              <FormField label="Late fee amount">
                <Input
                  type="number"
                  value={lateFeeAmount}
                  onChange={({ detail }) => setLateFeeAmount(detail.value)}
                />
              </FormField>
            )}
          </ColumnLayout>
          <FormField label="Description">
            <Input value={description} onChange={({ detail }) => setDescription(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>

      <Modal
        visible={depositOpen}
        onDismiss={() => setDepositOpen(false)}
        header="Record deposit"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setDepositOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={savingDeposit} onClick={saveDeposit}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Lease">
            <Select
              selectedOption={leaseOptions.find((o) => o.value === depLeaseId) ?? null}
              onChange={({ detail }) => setDepLeaseId(detail.selectedOption.value ?? '')}
              options={leaseOptions}
              filteringType="auto"
              placeholder="Select a lease"
            />
          </FormField>
          <FormField label="Amount">
            <Input type="number" value={depAmount} onChange={({ detail }) => setDepAmount(detail.value)} />
          </FormField>
          <FormField label="Notes">
            <Input value={depNotes} onChange={({ detail }) => setDepNotes(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default RentCollectionPage;
