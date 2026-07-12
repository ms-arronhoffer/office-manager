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
import { StorageManagerQuickCreate } from '@/components/common/QuickCreateForms';
import { selfStorage as api, leasing as leasingApi } from '@/api';
import type {
  StorageFacility,
  StorageFacilityCreate,
  StorageManager,
  StorageUnit,
  StorageUnitStatus,
  StorageUnitType,
  StorageAgreement,
  StorageAgreementStatus,
  StorageReservation,
  StorageRatePlan,
  StorageOccupancySummary,
  Resident,
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

// Human label for a Facility (the self-storage "Property") that acts as the
// parent of its storage units and agreements.
const facilityLabel = (f: StorageFacility) =>
  f.name || (f.facility_number != null ? `Facility ${f.facility_number}` : 'Facility');

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

// ─── Facilities (the self-storage "Property") ────────────────────────────────
const FacilitiesTab: React.FC<{
  canEdit: boolean;
  facilities: StorageFacility[];
  loading: boolean;
  reload: () => void;
}> = ({ canEdit, facilities, loading, reload }) => {
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Identity.
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [facilityNumber, setFacilityNumber] = useState('');
  const [isActive, setIsActive] = useState(true);
  // Address.
  const [addressLine1, setAddressLine1] = useState('');
  const [addressLine2, setAddressLine2] = useState('');
  const [city, setCity] = useState('');
  const [stateVal, setStateVal] = useState('');
  const [zipCode, setZipCode] = useState('');
  // Contact.
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  // Manager (its own data set — populates the drop-down).
  const [managerId, setManagerId] = useState('');
  const [managers, setManagers] = useState<StorageManager[]>([]);
  const [managerModalOpen, setManagerModalOpen] = useState(false);
  // Operations.
  const [gateHours, setGateHours] = useState('');
  const [accessHours, setAccessHours] = useState('');
  const [totalUnits, setTotalUnits] = useState('');
  const [notes, setNotes] = useState('');

  const loadManagers = useCallback(async () => {
    try {
      const res = await api.listManagers();
      setManagers(res.data);
    } catch {
      // Non-critical — the form is still usable without the manager list.
    }
  }, []);

  useEffect(() => {
    loadManagers();
  }, [loadManagers]);

  const resetForm = () => {
    setName('');
    setCode('');
    setFacilityNumber('');
    setIsActive(true);
    setAddressLine1('');
    setAddressLine2('');
    setCity('');
    setStateVal('');
    setZipCode('');
    setPhone('');
    setEmail('');
    setManagerId('');
    setGateHours('');
    setAccessHours('');
    setTotalUnits('');
    setNotes('');
    setError(null);
  };

  const submit = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('Property name is required.');
      return;
    }
    // Guard against non-numeric input for the numeric fields before hitting the API.
    if (facilityNumber.trim() && Number.isNaN(Number(facilityNumber))) {
      setError('Facility number must be a number.');
      return;
    }
    if (totalUnits.trim() && Number.isNaN(Number(totalUnits))) {
      setError('Total units must be a number.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: StorageFacilityCreate = {
        name: trimmedName,
        code: code.trim() || null,
        facility_number: facilityNumber.trim() ? Number(facilityNumber) : null,
        is_active: isActive,
        address_line_1: addressLine1.trim() || null,
        address_line_2: addressLine2.trim() || null,
        city: city.trim() || null,
        state: stateVal.trim() || null,
        zip_code: zipCode.trim() || null,
        phone: phone.trim() || null,
        email: email.trim() || null,
        manager_id: managerId || null,
        gate_hours: gateHours.trim() || null,
        access_hours: accessHours.trim() || null,
        total_units: totalUnits.trim() ? Number(totalUnits) : null,
        notes: notes.trim() || null,
      };
      await api.createFacility(payload);
      addFlash({ type: 'success', content: `Property "${trimmedName}" created.` });
      setOpen(false);
      resetForm();
      reload();
    } catch (e) {
      setError(errDetail(e, 'Failed to create the property.'));
    } finally {
      setSaving(false);
    }
  };

  const remove = (facility: StorageFacility) =>
    confirmDelete({
      itemName: facilityLabel(facility),
      onConfirm: async () => {
        try {
          await api.deleteFacility(facility.id);
          addFlash({ type: 'success', content: `Property "${facilityLabel(facility)}" deleted.` });
          reload();
        } catch (e) {
          addFlash({ type: 'error', content: errDetail(e, 'Failed to delete the property.') });
        }
      },
    });

  return (
    <>
      <Table
        loading={loading}
        items={facilities}
        variant="container"
        header={
          <Header
            counter={`(${facilities.length})`}
            description="Self-storage properties are their own data set — independent of the Commercial category."
            actions={
              canEdit ? (
                <Button variant="primary" onClick={() => setOpen(true)}>
                  Add property
                </Button>
              ) : undefined
            }
          >
            Properties
          </Header>
        }
        columnDefinitions={[
          { id: 'name', header: 'Name', cell: (f) => facilityLabel(f) },
          {
            id: 'location',
            header: 'Location',
            cell: (f) => [f.city, f.state].filter(Boolean).join(', ') || '—',
          },
          { id: 'manager', header: 'Manager', cell: (f) => f.manager?.name || f.manager_name || '—' },
          {
            id: 'active',
            header: 'Active',
            cell: (f) => (f.is_active ? <Badge color="green">Active</Badge> : <Badge color="grey">Inactive</Badge>),
          },
          ...(canEdit
            ? [
                {
                  id: 'actions',
                  header: '',
                  cell: (f: StorageFacility) => (
                    <Button variant="inline-link" onClick={() => remove(f)}>
                      Delete
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
        empty={<Box textAlign="center">No properties yet.</Box>}
      />
      <EntityFormModal
        visible={open}
        title="Add property"
        submitLabel="Create"
        submitting={saving}
        submitDisabled={!name.trim()}
        error={error}
        onSubmit={submit}
        onCancel={() => {
          setOpen(false);
          resetForm();
        }}
      >
        <SpaceBetween size="l">
          <Box variant="h4">Identity</Box>
          <ColumnLayout columns={2}>
            <FormField label="Name" constraintText="Required">
              <Input value={name} onChange={(e) => setName(e.detail.value)} placeholder="Downtown Storage" />
            </FormField>
            <FormField label="Code">
              <Input value={code} onChange={(e) => setCode(e.detail.value)} placeholder="DTS" />
            </FormField>
            <FormField label="Facility number">
              <Input
                value={facilityNumber}
                onChange={(e) => setFacilityNumber(e.detail.value)}
                type="number"
                inputMode="numeric"
              />
            </FormField>
            <FormField label="Active">
              <Toggle checked={isActive} onChange={(e) => setIsActive(e.detail.checked)}>
                {isActive ? 'Active' : 'Inactive'}
              </Toggle>
            </FormField>
          </ColumnLayout>

          <Box variant="h4">Address</Box>
          <FormField label="Address line 1">
            <Input
              value={addressLine1}
              onChange={(e) => setAddressLine1(e.detail.value)}
              placeholder="123 Main St"
            />
          </FormField>
          <FormField label="Address line 2">
            <Input
              value={addressLine2}
              onChange={(e) => setAddressLine2(e.detail.value)}
              placeholder="Suite 100"
            />
          </FormField>
          <ColumnLayout columns={3}>
            <FormField label="City">
              <Input value={city} onChange={(e) => setCity(e.detail.value)} />
            </FormField>
            <FormField label="State">
              <Input value={stateVal} onChange={(e) => setStateVal(e.detail.value)} placeholder="CO" />
            </FormField>
            <FormField label="ZIP code">
              <Input value={zipCode} onChange={(e) => setZipCode(e.detail.value)} placeholder="80202" />
            </FormField>
          </ColumnLayout>

          <Box variant="h4">Contact &amp; management</Box>
          <ColumnLayout columns={2}>
            <FormField label="Phone">
              <Input value={phone} onChange={(e) => setPhone(e.detail.value)} placeholder="555-1000" />
            </FormField>
            <FormField label="Email">
              <Input
                value={email}
                onChange={(e) => setEmail(e.detail.value)}
                type="email"
                placeholder="ops@example.com"
              />
            </FormField>
          </ColumnLayout>
          <FormField
            label="Manager"
            description="Managers are their own self-storage data set. Pick one or add a new manager."
          >
            <Select
              selectedOption={
                managerId
                  ? {
                      value: managerId,
                      label: managers.find((m) => m.id === managerId)?.name || 'Manager',
                    }
                  : { value: '', label: '— None —' }
              }
              onChange={(e) => {
                const value = e.detail.selectedOption.value || '';
                if (value === '__add__') {
                  setManagerModalOpen(true);
                  return;
                }
                setManagerId(value);
              }}
              options={[
                { value: '', label: '— None —' },
                ...managers.map((m) => ({ value: m.id, label: m.name })),
                { value: '__add__', label: '+ Add new manager…' },
              ]}
              placeholder="Select a manager"
            />
          </FormField>

          <Box variant="h4">Operations</Box>
          <ColumnLayout columns={2}>
            <FormField label="Gate hours">
              <Input value={gateHours} onChange={(e) => setGateHours(e.detail.value)} placeholder="6am–10pm" />
            </FormField>
            <FormField label="Access hours">
              <Input value={accessHours} onChange={(e) => setAccessHours(e.detail.value)} placeholder="24/7" />
            </FormField>
            <FormField label="Total units">
              <Input
                value={totalUnits}
                onChange={(e) => setTotalUnits(e.detail.value)}
                type="number"
                inputMode="numeric"
              />
            </FormField>
          </ColumnLayout>
          <FormField label="Notes">
            <Textarea value={notes} onChange={(e) => setNotes(e.detail.value)} />
          </FormField>
        </SpaceBetween>
      </EntityFormModal>
      <StorageManagerQuickCreate
        visible={managerModalOpen}
        onClose={() => setManagerModalOpen(false)}
        onCreated={(opt) => {
          // Refresh the manager list and select the newly-created manager.
          loadManagers();
          setManagerId(opt.value);
        }}
      />
      {deleteModal}
    </>
  );
};

// ─── Units ───────────────────────────────────────────────────────────────────
const UnitsTab: React.FC<{ canEdit: boolean; facilities: StorageFacility[] }> = ({ canEdit, facilities }) => {
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();
  const [units, setUnits] = useState<StorageUnit[]>([]);
  const [loading, setLoading] = useState(true);
  // Facility (Property) the units are scoped to; '' means all facilities.
  const [facilityFilter, setFacilityFilter] = useState('');

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unitNumber, setUnitNumber] = useState('');
  const [sizeLabel, setSizeLabel] = useState('');
  const [unitType, setUnitType] = useState<StorageUnitType>('interior');
  const [streetRate, setStreetRate] = useState('');
  const [climate, setClimate] = useState(false);
  const [facilityId, setFacilityId] = useState('');

  // Map a unit's facility_id to its Facility label for the table column.
  const facilityById = useMemo(
    () => new Map(facilities.map((f) => [f.id, facilityLabel(f)])),
    [facilities],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listUnits(facilityFilter ? { facility_id: facilityFilter } : undefined);
      setUnits(res.data);
    } catch (e) {
      addFlash({ type: 'error', content: errDetail(e, 'Failed to load storage units.') });
    } finally {
      setLoading(false);
    }
  }, [addFlash, facilityFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    // Default the new unit's Facility to the one currently being viewed.
    setFacilityId(facilityFilter);
    setOpen(true);
  };

  const resetForm = () => {
    setUnitNumber('');
    setSizeLabel('');
    setUnitType('interior');
    setStreetRate('');
    setClimate(false);
    setFacilityId('');
    setError(null);
  };

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createUnit({
        facility_id: facilityId || null,
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
      setError(errDetail(e, 'Failed to create the unit. Check the unit number is unique for this facility.'));
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
                    facilityFilter
                      ? { value: facilityFilter, label: facilityById.get(facilityFilter) || 'Facility' }
                      : { value: '', label: 'All facilities' }
                  }
                  onChange={(e) => setFacilityFilter(e.detail.selectedOption.value || '')}
                  options={[
                    { value: '', label: 'All facilities' },
                    ...facilities.map((f) => ({ value: f.id, label: facilityLabel(f) })),
                  ]}
                  ariaLabel="Filter units by facility"
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
            id: 'facility',
            header: 'Property',
            cell: (u) => (u.facility_id ? facilityById.get(u.facility_id) || '—' : 'Unassigned'),
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
            description="The facility this unit belongs to. Unit numbers are unique within a facility, so the same number can be reused across different facilities."
          >
            <Select
              selectedOption={
                facilityId
                  ? { value: facilityId, label: facilityById.get(facilityId) || 'Facility' }
                  : { value: '', label: 'Unassigned' }
              }
              onChange={(e) => setFacilityId(e.detail.selectedOption.value || '')}
              options={[
                { value: '', label: 'Unassigned' },
                ...facilities.map((f) => ({ value: f.id, label: facilityLabel(f) })),
              ]}
              placeholder="Select a facility"
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
const AGREEMENT_CREATE_STATUSES: StorageAgreementStatus[] = ['draft', 'active'];

const AgreementsTab: React.FC<{ canEdit: boolean }> = ({ canEdit }) => {
  const { addFlash } = useFlashbar();
  const [agreements, setAgreements] = useState<StorageAgreement[]>([]);
  const [loading, setLoading] = useState(true);

  // Reference data for the create form.
  const [units, setUnits] = useState<StorageUnit[]>([]);
  const [residents, setResidents] = useState<Resident[]>([]);

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unitId, setUnitId] = useState('');
  const [name, setName] = useState('');
  const [rent, setRent] = useState('');
  const [statusVal, setStatusVal] = useState<StorageAgreementStatus>('draft');
  const [moveInDate, setMoveInDate] = useState('');
  const [residentId, setResidentId] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listAgreements();
      setAgreements(res.data);
    } catch (e) {
      addFlash({ type: 'error', content: errDetail(e, 'Failed to load agreements.') });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  // Load units + residents lazily the first time the create form is opened so
  // the pickers are populated without slowing the initial table render.
  const openCreate = async () => {
    setOpen(true);
    try {
      const [unitsRes, residentsRes] = await Promise.all([
        api.listUnits(),
        leasingApi.listResidents(),
      ]);
      setUnits(unitsRes.data);
      setResidents(residentsRes.data);
    } catch (e) {
      setError(errDetail(e, 'Failed to load units or residents.'));
    }
  };

  const resetForm = () => {
    setUnitId('');
    setName('');
    setRent('');
    setStatusVal('draft');
    setMoveInDate('');
    setResidentId('');
    setError(null);
  };

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createAgreement({
        unit_id: unitId,
        name: name.trim() || null,
        status: statusVal,
        rent_amount: rent.trim() || null,
        move_in_date: moveInDate.trim() || null,
        occupants: residentId
          ? [{ resident_id: residentId, role: 'primary', is_primary: true }]
          : [],
      });
      addFlash({ type: 'success', content: 'Agreement created.' });
      setOpen(false);
      resetForm();
      load();
    } catch (e) {
      setError(errDetail(e, 'Failed to create the agreement.'));
    } finally {
      setSaving(false);
    }
  };

  const residentLabel = (r: Resident) =>
    [r.first_name, r.last_name].filter(Boolean).join(' ') || r.email || 'Resident';

  return (
    <>
      <Table
        loading={loading}
        items={agreements}
        variant="container"
        header={
          <Header
            counter={`(${agreements.length})`}
            actions={
              canEdit ? (
                <Button variant="primary" onClick={openCreate}>
                  Add agreement
                </Button>
              ) : undefined
            }
          >
            Rental agreements
          </Header>
        }
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
      <EntityFormModal
        visible={open}
        title="Add rental agreement"
        submitLabel="Create"
        submitting={saving}
        submitDisabled={!unitId}
        error={error}
        onSubmit={submit}
        onCancel={() => {
          setOpen(false);
          resetForm();
        }}
      >
        <SpaceBetween size="m">
          <FormField label="Unit" description="The storage unit this agreement rents.">
            <Select
              selectedOption={
                unitId
                  ? {
                      value: unitId,
                      label: units.find((u) => u.id === unitId)?.unit_number || 'Unit',
                    }
                  : null
              }
              onChange={(e) => setUnitId(e.detail.selectedOption.value || '')}
              options={units.map((u) => ({ value: u.id, label: u.unit_number }))}
              placeholder="Select a unit"
              empty="No units available"
            />
          </FormField>
          <FormField label="Name">
            <Input value={name} onChange={(e) => setName(e.detail.value)} placeholder="Smith — Unit A-101" />
          </FormField>
          <FormField label="Primary tenant" description="Optional; add or change occupants later.">
            <Select
              selectedOption={
                residentId
                  ? {
                      value: residentId,
                      label:
                        residents.find((r) => r.id === residentId)
                          ? residentLabel(residents.find((r) => r.id === residentId)!)
                          : 'Resident',
                    }
                  : { value: '', label: 'None' }
              }
              onChange={(e) => setResidentId(e.detail.selectedOption.value || '')}
              options={[
                { value: '', label: 'None' },
                ...residents.map((r) => ({ value: r.id, label: residentLabel(r) })),
              ]}
            />
          </FormField>
          <FormField label="Rent">
            <Input
              value={rent}
              onChange={(e) => setRent(e.detail.value)}
              type="number"
              inputMode="decimal"
              placeholder="0.00"
            />
          </FormField>
          <FormField label="Status">
            <Select
              selectedOption={{ value: statusVal, label: statusVal }}
              onChange={(e) => setStatusVal(e.detail.selectedOption.value as StorageAgreementStatus)}
              options={AGREEMENT_CREATE_STATUSES.map((s) => ({ value: s, label: s }))}
            />
          </FormField>
          <FormField label="Move-in date">
            <Input
              value={moveInDate}
              onChange={(e) => setMoveInDate(e.detail.value)}
              type="date"
              placeholder="YYYY-MM-DD"
            />
          </FormField>
        </SpaceBetween>
      </EntityFormModal>
    </>
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

  // Facilities (self-storage "Properties") are the parent of storage units and
  // agreements. They are their own data set (not commercial Offices), so self
  // storage works even when the Commercial category is turned off. Loaded here
  // and shared with the Properties, Units, and other tabs.
  const [facilities, setFacilities] = useState<StorageFacility[]>([]);
  const [facilitiesLoading, setFacilitiesLoading] = useState(true);

  const loadFacilities = useCallback(() => {
    setFacilitiesLoading(true);
    api
      .listFacilities()
      .then((res) => setFacilities(res.data))
      .catch((e) => {
        setFacilities([]);
        addFlash({
          type: 'warning',
          content: errDetail(e, 'Failed to load properties; unit locations may be unavailable.'),
        });
      })
      .finally(() => setFacilitiesLoading(false));
  }, [addFlash]);

  useEffect(() => {
    loadFacilities();
  }, [loadFacilities]);

  const tabs: TabbedPageTab[] = useMemo(
    () => [
      { id: 'overview', label: 'Overview', href: '/self-storage', content: <OverviewTab /> },
      {
        id: 'properties',
        label: 'Properties',
        href: '/self-storage/properties',
        content: (
          <FacilitiesTab
            canEdit={canEdit}
            facilities={facilities}
            loading={facilitiesLoading}
            reload={loadFacilities}
          />
        ),
      },
      {
        id: 'units',
        label: 'Units',
        href: '/self-storage/units',
        content: <UnitsTab canEdit={canEdit} facilities={facilities} />,
      },
      {
        id: 'agreements',
        label: 'Agreements',
        href: '/self-storage/agreements',
        content: <AgreementsTab canEdit={canEdit} />,
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
    [canEdit, facilities, facilitiesLoading, loadFacilities],
  );

  return <TabbedPage ariaLabel="Self Storage" tabs={tabs} />;
};

export default SelfStoragePage;
