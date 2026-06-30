import React, { useCallback, useEffect, useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Tabs from '@cloudscape-design/components/tabs';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Toggle from '@cloudscape-design/components/toggle';
import Textarea from '@cloudscape-design/components/textarea';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Table from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import { useFlashbar } from '@/context/FlashbarContext';
import {
  superAdmin,
  type AdminOrgDetail,
  type BillingDetail,
  type EntitlementValue,
  type EntitlementsCatalog,
} from '@/api/superAdmin';

const usd = (cents: number | null | undefined) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(
    (cents ?? 0) / 100,
  );

const PAYMENT_STATUSES = ['trialing', 'active', 'past_due', 'canceled'];
const PLANS = ['starter', 'pro', 'enterprise'];

const renderVal = (v: EntitlementValue | undefined) => {
  if (v === true) return 'enabled';
  if (v === false) return 'disabled';
  if (v === null || v === undefined) return 'unlimited';
  return String(v);
};

interface Props {
  orgId: string;
  onDismiss: () => void;
  onSaved: () => void;
}

const OrgManageModal: React.FC<Props> = ({ orgId, onDismiss, onSaved }) => {
  const { addFlash } = useFlashbar();
  const [org, setOrg] = useState<AdminOrgDetail | null>(null);
  const [catalog, setCatalog] = useState<EntitlementsCatalog | null>(null);
  const [billing, setBilling] = useState<BillingDetail | null>(null);
  const [saving, setSaving] = useState(false);
  const [creditAmount, setCreditAmount] = useState('');
  const [creditReason, setCreditReason] = useState('');

  const load = useCallback(() => {
    superAdmin
      .getOrg(orgId)
      .then((r) => setOrg(r.data))
      .catch(() => addFlash({ type: 'error', content: 'Failed to load organization.' }));
    superAdmin.orgCatalog(orgId).then((r) => setCatalog(r.data)).catch(() => undefined);
    superAdmin.billingDetail(orgId).then((r) => setBilling(r.data)).catch(() => setBilling(null));
  }, [orgId, addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const set = (patch: Partial<AdminOrgDetail>) => setOrg((o) => (o ? { ...o, ...patch } : o));
  const setOverride = (key: string, val: EntitlementValue) =>
    setOrg((o) => (o ? { ...o, entitlement_overrides: { ...o.entitlement_overrides, [key]: val } } : o));
  const clearOverride = (key: string) =>
    setOrg((o) => {
      if (!o) return o;
      const next = { ...o.entitlement_overrides };
      delete next[key];
      return { ...o, entitlement_overrides: next };
    });

  const save = async () => {
    if (!org) return;
    setSaving(true);
    try {
      await superAdmin.patchOrg(orgId, {
        name: org.name,
        plan: org.plan,
        is_active: org.is_active,
        payment_status: org.payment_status,
        max_seats: org.max_seats,
        admin_notes: org.admin_notes,
        entitlement_overrides: org.entitlement_overrides,
      });
      addFlash({ type: 'success', content: 'Organization updated.' });
      onSaved();
    } catch {
      addFlash({ type: 'error', content: 'Update failed.' });
    } finally {
      setSaving(false);
    }
  };

  const credit = async () => {
    const cents = Math.round(parseFloat(creditAmount) * 100);
    if (!Number.isFinite(cents) || cents === 0) {
      addFlash({ type: 'error', content: 'Enter a non-zero credit amount.' });
      return;
    }
    try {
      await superAdmin.issueCredit(orgId, cents, creditReason || undefined);
      addFlash({ type: 'success', content: 'Credit issued.' });
      setCreditAmount('');
      setCreditReason('');
      load();
    } catch {
      addFlash({ type: 'error', content: 'Credit failed.' });
    }
  };

  if (!org) {
    return (
      <Modal visible onDismiss={onDismiss} header="Manage organization">
        <StatusIndicator type="loading">Loading…</StatusIndicator>
      </Modal>
    );
  }

  const limitKeys = catalog?.limit_keys ?? [];
  const featureKeys = catalog?.feature_keys ?? [];

  return (
    <Modal
      visible
      onDismiss={onDismiss}
      size="large"
      header={`Manage ${org.name}`}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Close
            </Button>
            <Button variant="primary" loading={saving} onClick={save}>
              Save changes
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <Tabs
        tabs={[
          {
            id: 'profile',
            label: 'Profile',
            content: (
              <SpaceBetween size="m">
                <FormField label="Name">
                  <Input value={org.name} onChange={({ detail }) => set({ name: detail.value })} />
                </FormField>
                <FormField label="Plan">
                  <Select
                    selectedOption={{ value: org.plan, label: org.plan }}
                    options={PLANS.map((p) => ({ value: p, label: p }))}
                    onChange={({ detail }) => set({ plan: detail.selectedOption.value })}
                  />
                </FormField>
                <FormField label="Payment status">
                  <Select
                    selectedOption={{ value: org.payment_status, label: org.payment_status }}
                    options={PAYMENT_STATUSES.map((p) => ({ value: p, label: p }))}
                    onChange={({ detail }) => set({ payment_status: detail.selectedOption.value })}
                  />
                </FormField>
                <FormField label="Max seats (blank = unlimited)">
                  <Input
                    type="number"
                    value={org.max_seats === null ? '' : String(org.max_seats)}
                    onChange={({ detail }) =>
                      set({ max_seats: detail.value === '' ? null : Number(detail.value) })
                    }
                  />
                </FormField>
                <Toggle checked={org.is_active} onChange={({ detail }) => set({ is_active: detail.checked })}>
                  Active
                </Toggle>
                <FormField label="Admin notes">
                  <Textarea value={org.admin_notes ?? ''} onChange={({ detail }) => set({ admin_notes: detail.value })} />
                </FormField>
                <KeyValuePairs
                  columns={3}
                  items={[
                    { label: 'Slug', value: org.slug },
                    { label: 'Offices', value: String(org.office_count) },
                    { label: 'Seats in use', value: String(org.seat_count) },
                    { label: 'Open tickets', value: String(org.open_ticket_count) },
                    { label: 'Stripe customer', value: org.stripe_customer_id ?? '—' },
                    { label: 'Created', value: org.created_at?.slice(0, 10) ?? '—' },
                  ]}
                />
              </SpaceBetween>
            ),
          },
          {
            id: 'entitlements',
            label: 'Entitlements',
            content: (
              <SpaceBetween size="m">
                <Table
                  variant="embedded"
                  header={<Header variant="h3">Limits</Header>}
                  items={limitKeys}
                  columnDefinitions={[
                    { id: 'key', header: 'Limit', cell: (k) => k },
                    { id: 'default', header: 'Plan default', cell: (k) => renderVal(org.plan_defaults[k]) },
                    {
                      id: 'override',
                      header: 'Override',
                      cell: (k) => (
                        <Input
                          type="number"
                          value={
                            org.entitlement_overrides[k] === undefined || org.entitlement_overrides[k] === null
                              ? ''
                              : String(org.entitlement_overrides[k])
                          }
                          placeholder="default"
                          onChange={({ detail }) =>
                            detail.value === '' ? clearOverride(k) : setOverride(k, Number(detail.value))
                          }
                        />
                      ),
                    },
                  ]}
                  empty="No limits."
                />
                <Table
                  variant="embedded"
                  header={<Header variant="h3">Features</Header>}
                  items={featureKeys}
                  columnDefinitions={[
                    { id: 'key', header: 'Feature', cell: (k) => k },
                    { id: 'default', header: 'Plan default', cell: (k) => renderVal(org.plan_defaults[k]) },
                    {
                      id: 'override',
                      header: 'Override',
                      cell: (k) => (
                        <Select
                          selectedOption={{
                            value: String(org.entitlement_overrides[k] ?? 'default'),
                            label:
                              org.entitlement_overrides[k] === undefined
                                ? 'default'
                                : org.entitlement_overrides[k]
                                  ? 'enabled'
                                  : 'disabled',
                          }}
                          options={[
                            { value: 'default', label: 'default' },
                            { value: 'true', label: 'enabled' },
                            { value: 'false', label: 'disabled' },
                          ]}
                          onChange={({ detail }) =>
                            detail.selectedOption.value === 'default'
                              ? clearOverride(k)
                              : setOverride(k, detail.selectedOption.value === 'true')
                          }
                        />
                      ),
                    },
                  ]}
                  empty="No features."
                />
              </SpaceBetween>
            ),
          },
          {
            id: 'billing',
            label: 'Billing',
            content: billing ? (
              <SpaceBetween size="m">
                <KeyValuePairs
                  columns={3}
                  items={[
                    { label: 'Plan', value: billing.plan },
                    { label: 'Status', value: billing.payment_status },
                    { label: 'Credit balance', value: usd(billing.credit_balance_cents) },
                  ]}
                />
                <SpaceBetween direction="horizontal" size="xs">
                  <FormField label="Credit amount ($)">
                    <Input type="number" value={creditAmount} onChange={({ detail }) => setCreditAmount(detail.value)} />
                  </FormField>
                  <FormField label="Reason">
                    <Input value={creditReason} onChange={({ detail }) => setCreditReason(detail.value)} />
                  </FormField>
                  <Box padding={{ top: 'xl' }}>
                    <Button onClick={credit}>Issue credit</Button>
                  </Box>
                </SpaceBetween>
                <Table
                  variant="embedded"
                  header={<Header variant="h3">Invoices</Header>}
                  items={billing.invoices}
                  columnDefinitions={[
                    { id: 'number', header: 'Number', cell: (i) => String(i.number ?? i.id ?? '—') },
                    { id: 'status', header: 'Status', cell: (i) => String(i.status ?? '—') },
                    { id: 'total', header: 'Total', cell: (i) => usd(i.total_cents as number | null | undefined) },
                    { id: 'issued', header: 'Issued', cell: (i) => String(i.issued_at ?? '—').slice(0, 10) },
                  ]}
                  empty="No invoices."
                />
              </SpaceBetween>
            ) : (
              <Box color="text-status-inactive">No billing ledger data for this org.</Box>
            ),
          },
        ]}
      />
    </Modal>
  );
};

export default OrgManageModal;
