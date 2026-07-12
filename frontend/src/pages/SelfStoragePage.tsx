import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Toggle from '@cloudscape-design/components/toggle';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';
import EntityFormModal from '@/components/common/EntityFormModal';
import { selfStorage as api, offices as officesApi } from '@/api';
import type {
  Office,
  StorageUnit,
  StorageUnitStatus,
  StorageUnitType,
  StorageAgreement,
  StorageAgreementStatus,
  StorageReservation,
  StorageRatePlan,
  StorageOccupancySummary,
} from '@/types';

const UNIT_TYPES: StorageUnitType[] = [
  'drive_up',
  'interior',
  'outdoor',
  'locker',
  'vehicle',
  'parking',
];

const fmtMoney = (v?: string | null) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

// Human label for a Property (Location / Office) that acts as the parent of
// its storage units.
const propertyLabel = (o: Office) =>
  o.location_name || (o.office_number != null ? `Property ${o.office_number}` : 'Property');

// Pull the server-provided error detail (e.g. a disabled-category or
// validation message) out of an Axios error so the flashbar can explain *why*
// a load failed instead of showing a generic message.
const errDetail = (e: unknown, fallback: string): string =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

const unitStatusBadge = (s: StorageUnitStatus) => {
  const color =
    s === 'available'
      ? 'green'
      : s === 'occupied' || s === 'reserved'
        ? 'blue'
        : s === 'lien' || s === 'auction'
          ? 'red'
          : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'red' | 'grey'}>{s}</Badge>;
};

const agreementStatusBadge = (s: StorageAgreementStatus) => {
  const color =
    s === 'active'
      ? 'green'
      : s === 'delinquent' || s === 'in_lien' || s === 'auctioned'
        ? 'red'
        : s === 'draft'
          ? 'grey'
          : 'blue';
  return <Badge color={color as 'green' | 'red' | 'grey' | 'blue'}>{s}</Badge>;
};

// ─── Overview ────────────────────────────────────────────────────────────────
const OverviewTab: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [summary, setSummary] = useState<StorageOccupancySummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .occupancySummary()
      .then((res) => active && setSummary(res.data))
      .catch((e) => active && addFlash({ type: 'error', content: errDetail(e, 'Failed to load occupancy summary.') }))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [addFlash]);

  return (
    <Container header={<Header variant="h2">Occupancy & revenue</Header>}>
      {loading ? (
        <Box>Loading…</Box>
      ) : summary ? (
        <ColumnLayout columns={4} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Total units</Box>
            <Box variant="h2">{summary.total_units}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Occupied</Box>
            <Box variant="h2">{summary.occupied_units}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Available</Box>
            <Box variant="h2">{summary.available_units}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Physical occupancy</Box>
            <Box variant="h2">{summary.physical_occupancy_pct}%</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Economic occupancy</Box>
            <Box variant="h2">{summary.economic_occupancy_pct}%</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Potential monthly revenue</Box>
            <Box variant="h2">{fmtMoney(summary.potential_monthly_revenue)}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">In-place monthly revenue</Box>
            <Box variant="h2">{fmtMoney(summary.in_place_monthly_revenue)}</Box>
          </div>
        </ColumnLayout>
      ) : (
        <Box>No data.</Box>
      )}
    </Container>
  );
};

// ─── Units ───────────────────────────────────────────────────────────────────
const UnitsTab: React.FC<{ canEdit: boolean; properties: Office[] }> = ({ canEdit, properties }) => {
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();
  const [units, setUnits] = useState<StorageUnit[]>([]);
  const [loading, setLoading] = useState(true);
  // Property (Location) the units are scoped to; '' means all properties.
  const [officeFilter, setOfficeFilter] = useState('');

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unitNumber, setUnitNumber] = useState('');
  const [sizeLabel, setSizeLabel] = useState('');
  const [unitType, setUnitType] = useState<StorageUnitType>('interior');
  const [streetRate, setStreetRate] = useState('');
  const [climate, setClimate] = useState(false);
  const [officeId, setOfficeId] = useState('');

  // Map a unit's office_id to its Property label for the table column.
  const propertyById = useMemo(
    () => new Map(properties.map((p) => [p.id, propertyLabel(p)])),
    [properties],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listUnits(officeFilter ? { office_id: officeFilter } : undefined);
      setUnits(res.data);
    } catch (e) {
      addFlash({ type: 'error', content: errDetail(e, 'Failed to load storage units.') });
    } finally {
      setLoading(false);
    }
  }, [addFlash, officeFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    // Default the new unit's Property to the one currently being viewed.
    setOfficeId(officeFilter);
    setOpen(true);
  };

  const resetForm = () => {
    setUnitNumber('');
    setSizeLabel('');
    setUnitType('interior');
    setStreetRate('');
    setClimate(false);
    setOfficeId('');
    setError(null);
  };

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createUnit({
        office_id: officeId || null,
        unit_number: unitNumber.trim(),
        size_label: sizeLabel.trim() || null,
        unit_type: unitType,
        climate_controlled: climate,
        street_rate: streetRate.trim() || null,
      });
      addFlash({ type: 'success', content: `Unit ${unitNumber} created.` });
      setOpen(false);
      resetForm();
      load();
    } catch (e) {
      setError(errDetail(e, 'Failed to create the unit. Check the unit number is unique for this property.'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (unit: StorageUnit) =>
    confirmDelete({
      itemName: `Unit ${unit.unit_number}`,
      onConfirm: async () => {
        try {
          await api.deleteUnit(unit.id);
          addFlash({ type: 'success', content: `Unit ${unit.unit_number} deleted.` });
          load();
        } catch (e) {
          addFlash({ type: 'error', content: errDetail(e, 'Failed to delete the unit.') });
        }
      },
    });

  return (
    <>
      <Table
        loading={loading}
        items={units}
        variant="container"
        header={
          <Header
            counter={`(${units.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Select
                  selectedOption={
                    officeFilter
                      ? { value: officeFilter, label: propertyById.get(officeFilter) || 'Property' }
                      : { value: '', label: 'All properties' }
                  }
                  onChange={(e) => setOfficeFilter(e.detail.selectedOption.value || '')}
                  options={[
                    { value: '', label: 'All properties' },
                    ...properties.map((p) => ({ value: p.id, label: propertyLabel(p) })),
                  ]}
                  ariaLabel="Filter units by property"
                />
                {canEdit ? (
                  <Button variant="primary" onClick={openCreate}>
                    Add unit
                  </Button>
                ) : null}
              </SpaceBetween>
            }
          >
            Units
          </Header>
        }
        columnDefinitions={[
          { id: 'unit_number', header: 'Unit', cell: (u) => u.unit_number },
          {
            id: 'property',
            header: 'Property',
            cell: (u) => (u.office_id ? propertyById.get(u.office_id) || '—' : 'Unassigned'),
          },
          { id: 'size', header: 'Size', cell: (u) => u.size_label || u.size_tier || '—' },
          { id: 'type', header: 'Type', cell: (u) => u.unit_type },
          {
            id: 'climate',
            header: 'Climate',
            cell: (u) => (u.climate_controlled ? 'Yes' : 'No'),
          },
          { id: 'street_rate', header: 'Street rate', cell: (u) => fmtMoney(u.street_rate) },
          { id: 'status', header: 'Status', cell: (u) => unitStatusBadge(u.status) },
          ...(canEdit
            ? [
                {
                  id: 'actions',
                  header: '',
                  cell: (u: StorageUnit) => (
                    <Button variant="inline-link" onClick={() => remove(u)}>
                      Delete
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
        empty={<Box textAlign="center">No storage units yet.</Box>}
      />
      <EntityFormModal
        visible={open}
        title="Add storage unit"
        submitLabel="Create"
        submitting={saving}
        submitDisabled={!unitNumber.trim()}
        error={error}
        onSubmit={submit}
        onCancel={() => {
          setOpen(false);
          resetForm();
        }}
      >
        <SpaceBetween size="m">
          <FormField
            label="Property"
            description="The location this unit belongs to. Unit numbers are unique within a property, so the same number can exist at multiple properties."
          >
            <Select
              selectedOption={
                officeId
                  ? { value: officeId, label: propertyById.get(officeId) || 'Property' }
                  : { value: '', label: 'Unassigned' }
              }
              onChange={(e) => setOfficeId(e.detail.selectedOption.value || '')}
              options={[
                { value: '', label: 'Unassigned' },
                ...properties.map((p) => ({ value: p.id, label: propertyLabel(p) })),
              ]}
              placeholder="Select a property"
            />
          </FormField>
          <FormField label="Unit number">
            <Input
              value={unitNumber}
              onChange={(e) => setUnitNumber(e.detail.value)}
              placeholder="A-101"
            />
          </FormField>
          <FormField label="Size label">
            <Input
              value={sizeLabel}
              onChange={(e) => setSizeLabel(e.detail.value)}
              placeholder="10x10"
            />
          </FormField>
          <FormField label="Unit type">
            <Select
              selectedOption={{ value: unitType, label: unitType }}
              onChange={(e) => setUnitType(e.detail.selectedOption.value as StorageUnitType)}
              options={UNIT_TYPES.map((t) => ({ value: t, label: t }))}
            />
          </FormField>
          <FormField label="Street rate">
            <Input
              value={streetRate}
              onChange={(e) => setStreetRate(e.detail.value)}
              type="number"
              inputMode="decimal"
              placeholder="0.00"
            />
          </FormField>
          <FormField label="Climate controlled">
            <Toggle checked={climate} onChange={(e) => setClimate(e.detail.checked)}>
              Climate controlled
            </Toggle>
          </FormField>
        </SpaceBetween>
      </EntityFormModal>
      {deleteModal}
    </>
  );
};

// ─── Agreements ──────────────────────────────────────────────────────────────
const AgreementsTab: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [agreements, setAgreements] = useState<StorageAgreement[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .listAgreements()
      .then((res) => active && setAgreements(res.data))
      .catch((e) => active && addFlash({ type: 'error', content: errDetail(e, 'Failed to load agreements.') }))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [addFlash]);

  return (
    <Table
      loading={loading}
      items={agreements}
      variant="container"
      header={<Header counter={`(${agreements.length})`}>Rental agreements</Header>}
      columnDefinitions={[
        { id: 'name', header: 'Name', cell: (a) => a.name || '—' },
        { id: 'status', header: 'Status', cell: (a) => agreementStatusBadge(a.status) },
        { id: 'rent', header: 'Rent', cell: (a) => fmtMoney(a.rent_amount) },
        { id: 'move_in', header: 'Move-in', cell: (a) => a.move_in_date || '—' },
        {
          id: 'occupants',
          header: 'Occupants',
          cell: (a) => (a.occupants?.length ?? 0).toString(),
        },
        { id: 'autopay', header: 'Autopay', cell: (a) => (a.autopay_enabled ? 'Yes' : 'No') },
      ]}
      empty={<Box textAlign="center">No agreements yet.</Box>}
    />
  );
};

// ─── Reservations ────────────────────────────────────────────────────────────
const ReservationsTab: React.FC<{ canEdit: boolean }> = ({ canEdit }) => {
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();
  const [reservations, setReservations] = useState<StorageReservation[]>([]);
  const [loading, setLoading] = useState(true);

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [sizeTier, setSizeTier] = useState('');
  const [quotedRate, setQuotedRate] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listReservations();
      setReservations(res.data);
    } catch (e) {
      addFlash({ type: 'error', content: errDetail(e, 'Failed to load reservations.') });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createReservation({
        prospect_name: name.trim() || null,
        prospect_email: email.trim() || null,
        size_tier: sizeTier.trim() || null,
        quoted_rate: quotedRate.trim() || null,
        status: 'held',
      });
      addFlash({ type: 'success', content: 'Reservation created.' });
      setOpen(false);
      setName('');
      setEmail('');
      setSizeTier('');
      setQuotedRate('');
      load();
    } catch (e) {
      setError(errDetail(e, 'Failed to create the reservation.'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (r: StorageReservation) =>
    confirmDelete({
      itemName: r.prospect_name || 'Reservation',
      onConfirm: async () => {
        try {
          await api.deleteReservation(r.id);
          addFlash({ type: 'success', content: 'Reservation deleted.' });
          load();
        } catch (e) {
          addFlash({ type: 'error', content: errDetail(e, 'Failed to delete the reservation.') });
        }
      },
    });

  return (
    <>
      <Table
        loading={loading}
        items={reservations}
        variant="container"
        header={
          <Header
            counter={`(${reservations.length})`}
            actions={
              canEdit ? (
                <Button variant="primary" onClick={() => setOpen(true)}>
                  Add reservation
                </Button>
              ) : undefined
            }
          >
            Reservations
          </Header>
        }
        columnDefinitions={[
          { id: 'name', header: 'Prospect', cell: (r) => r.prospect_name || '—' },
          { id: 'email', header: 'Email', cell: (r) => r.prospect_email || '—' },
          { id: 'size', header: 'Size tier', cell: (r) => r.size_tier || '—' },
          { id: 'rate', header: 'Quoted rate', cell: (r) => fmtMoney(r.quoted_rate) },
          { id: 'status', header: 'Status', cell: (r) => <Badge>{r.status}</Badge> },
          { id: 'hold', header: 'Hold until', cell: (r) => r.hold_until || '—' },
          ...(canEdit
            ? [
                {
                  id: 'actions',
                  header: '',
                  cell: (r: StorageReservation) => (
                    <Button variant="inline-link" onClick={() => remove(r)}>
                      Delete
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
        empty={<Box textAlign="center">No reservations yet.</Box>}
      />
      <EntityFormModal
        visible={open}
        title="Add reservation"
        submitLabel="Create"
        submitting={saving}
        error={error}
        onSubmit={submit}
        onCancel={() => setOpen(false)}
      >
        <SpaceBetween size="m">
          <FormField label="Prospect name">
            <Input value={name} onChange={(e) => setName(e.detail.value)} />
          </FormField>
          <FormField label="Prospect email">
            <Input value={email} onChange={(e) => setEmail(e.detail.value)} type="email" />
          </FormField>
          <FormField label="Size tier">
            <Input value={sizeTier} onChange={(e) => setSizeTier(e.detail.value)} />
          </FormField>
          <FormField label="Quoted rate">
            <Input
              value={quotedRate}
              onChange={(e) => setQuotedRate(e.detail.value)}
              type="number"
              inputMode="decimal"
            />
          </FormField>
        </SpaceBetween>
      </EntityFormModal>
      {deleteModal}
    </>
  );
};

// ─── Rate plans ──────────────────────────────────────────────────────────────
const RatePlansTab: React.FC<{ canEdit: boolean }> = ({ canEdit }) => {
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();
  const [plans, setPlans] = useState<StorageRatePlan[]>([]);
  const [loading, setLoading] = useState(true);

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sizeTier, setSizeTier] = useState('');
  const [name, setName] = useState('');
  const [streetRate, setStreetRate] = useState('');
  const [standardRate, setStandardRate] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listRatePlans();
      setPlans(res.data);
    } catch (e) {
      addFlash({ type: 'error', content: errDetail(e, 'Failed to load rate plans.') });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createRatePlan({
        size_tier: sizeTier.trim(),
        name: name.trim() || null,
        street_rate: streetRate.trim() || null,
        standard_rate: standardRate.trim() || null,
        active: true,
      });
      addFlash({ type: 'success', content: 'Rate plan created.' });
      setOpen(false);
      setSizeTier('');
      setName('');
      setStreetRate('');
      setStandardRate('');
      load();
    } catch (e) {
      setError(errDetail(e, 'Failed to create the rate plan.'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (p: StorageRatePlan) =>
    confirmDelete({
      itemName: p.name || p.size_tier,
      onConfirm: async () => {
        try {
          await api.deleteRatePlan(p.id);
          addFlash({ type: 'success', content: 'Rate plan deleted.' });
          load();
        } catch (e) {
          addFlash({ type: 'error', content: errDetail(e, 'Failed to delete the rate plan.') });
        }
      },
    });

  return (
    <>
      <Table
        loading={loading}
        items={plans}
        variant="container"
        header={
          <Header
            counter={`(${plans.length})`}
            actions={
              canEdit ? (
                <Button variant="primary" onClick={() => setOpen(true)}>
                  Add rate plan
                </Button>
              ) : undefined
            }
          >
            Rate plans
          </Header>
        }
        columnDefinitions={[
          { id: 'size', header: 'Size tier', cell: (p) => p.size_tier },
          { id: 'name', header: 'Name', cell: (p) => p.name || '—' },
          { id: 'street', header: 'Street rate', cell: (p) => fmtMoney(p.street_rate) },
          { id: 'standard', header: 'Standard rate', cell: (p) => fmtMoney(p.standard_rate) },
          {
            id: 'active',
            header: 'Active',
            cell: (p) => (p.active ? <Badge color="green">Active</Badge> : <Badge color="grey">Inactive</Badge>),
          },
          ...(canEdit
            ? [
                {
                  id: 'actions',
                  header: '',
                  cell: (p: StorageRatePlan) => (
                    <Button variant="inline-link" onClick={() => remove(p)}>
                      Delete
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
        empty={<Box textAlign="center">No rate plans yet.</Box>}
      />
      <EntityFormModal
        visible={open}
        title="Add rate plan"
        submitLabel="Create"
        submitting={saving}
        submitDisabled={!sizeTier.trim()}
        error={error}
        onSubmit={submit}
        onCancel={() => setOpen(false)}
      >
        <SpaceBetween size="m">
          <FormField label="Size tier">
            <Input value={sizeTier} onChange={(e) => setSizeTier(e.detail.value)} placeholder="10x10" />
          </FormField>
          <FormField label="Name">
            <Input value={name} onChange={(e) => setName(e.detail.value)} />
          </FormField>
          <FormField label="Street rate">
            <Input
              value={streetRate}
              onChange={(e) => setStreetRate(e.detail.value)}
              type="number"
              inputMode="decimal"
            />
          </FormField>
          <FormField label="Standard rate">
            <Input
              value={standardRate}
              onChange={(e) => setStandardRate(e.detail.value)}
              type="number"
              inputMode="decimal"
            />
          </FormField>
        </SpaceBetween>
      </EntityFormModal>
      {deleteModal}
    </>
  );
};

/**
 * "Self Storage" hub — the third primary category alongside Commercial and
 * Residential. Surfaces facility management (units, agreements, reservations,
 * rate plans) as URL-driven tabs, mirroring the ResidentialPage / FinancePage
 * pattern.
 */
const SelfStoragePage: React.FC = () => {
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  // Properties (Locations / Offices) are the parent of storage units — a unit
  // number like "100" can exist under several properties. Loaded once and
  // shared with the Units tab so it can display, filter, and assign them.
  const [properties, setProperties] = useState<Office[]>([]);
  useEffect(() => {
    let active = true;
    officesApi
      .list({ page_size: 1000 })
      .then((res) => {
        if (active) setProperties(res.data.items);
      })
      .catch((e) => {
        // Non-fatal: units still render, just without property labels. Warn so
        // the user understands why property names may be missing.
        if (!active) return;
        setProperties([]);
        addFlash({
          type: 'warning',
          content: errDetail(e, 'Failed to load properties; unit locations may be unavailable.'),
        });
      });
    return () => {
      active = false;
    };
  }, [addFlash]);

  const tabs: TabbedPageTab[] = useMemo(
    () => [
      { id: 'overview', label: 'Overview', href: '/self-storage', content: <OverviewTab /> },
      {
        id: 'units',
        label: 'Units',
        href: '/self-storage/units',
        content: <UnitsTab canEdit={canEdit} properties={properties} />,
      },
      {
        id: 'agreements',
        label: 'Agreements',
        href: '/self-storage/agreements',
        content: <AgreementsTab />,
      },
      {
        id: 'reservations',
        label: 'Reservations',
        href: '/self-storage/reservations',
        content: <ReservationsTab canEdit={canEdit} />,
      },
      {
        id: 'rate-plans',
        label: 'Rate plans',
        href: '/self-storage/rate-plans',
        content: <RatePlansTab canEdit={canEdit} />,
      },
    ],
    [canEdit, properties],
  );

  return <TabbedPage ariaLabel="Self Storage" tabs={tabs} />;
};

export default SelfStoragePage;
