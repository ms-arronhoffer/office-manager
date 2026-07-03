import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { useAuth } from '@/auth/AuthContext';
import { leasing, offices as officesApi, attachments as attachmentsApi } from '@/api';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import EntityFormModal from '@/components/common/EntityFormModal';
import FileUploadField, { type QueuedFile } from '@/components/common/FileUploadField';
import type { RentalUnit, UnitStatus, Office, OccupancySummary } from '@/types';

const fmtMoney = (v: string | null) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const UNIT_STATUSES: UnitStatus[] = ['available', 'occupied', 'unavailable'];

const unitBadge = (s: UnitStatus) => {
  const color = s === 'available' ? 'green' : s === 'occupied' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

interface Opt { label: string; value: string; }

const LeasingUnitsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const { user } = useAuth();
  const canEditDocuments = user?.role === 'admin' || user?.role === 'editor';
  const [units, setUnits] = useState<RentalUnit[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [occupancy, setOccupancy] = useState<OccupancySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<Opt>({ label: 'All statuses', value: '' });

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<RentalUnit | null>(null);
  const [officeId, setOfficeId] = useState('');
  const [unitNumber, setUnitNumber] = useState('');
  const [name, setName] = useState('');
  const [floor, setFloor] = useState('');
  const [bedrooms, setBedrooms] = useState('');
  const [bathrooms, setBathrooms] = useState('');
  const [squareFeet, setSquareFeet] = useState('');
  const [marketRent, setMarketRent] = useState('');
  const [statusValue, setStatusValue] = useState<UnitStatus>('available');
  const [addr1, setAddr1] = useState('');
  const [addr2, setAddr2] = useState('');
  const [city, setCity] = useState('');
  const [stateVal, setStateVal] = useState('');
  const [zip, setZip] = useState('');
  const [propertyType, setPropertyType] = useState('');
  const [yearBuilt, setYearBuilt] = useState('');
  const [availableDate, setAvailableDate] = useState('');
  const [description, setDescription] = useState('');
  const [amenities, setAmenities] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = statusFilter.value ? { status: statusFilter.value } : undefined;
      const [u, occ] = await Promise.all([
        leasing.listUnits(params),
        leasing.occupancy(),
      ]);
      setUnits(u.data);
      setOccupancy(occ.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load rental units.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash, statusFilter.value]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    officesApi
      .list({ page_size: 200 })
      .then((r) => setOffices(r.data.items))
      .catch(() => undefined);
  }, []);

  const officeOptions: Opt[] = useMemo(
    () => [
      { label: '— No property —', value: '' },
      ...offices.map((o) => ({
        label: `${o.office_number} · ${o.location_name}`,
        value: o.id,
      })),
    ],
    [offices],
  );

  const officeLabel = useCallback(
    (id: string | null) => {
      if (!id) return '—';
      const o = offices.find((x) => x.id === id);
      return o ? `${o.office_number} · ${o.location_name}` : id;
    },
    [offices],
  );

  const openCreate = () => {
    setEditing(null);
    setOfficeId('');
    setUnitNumber('');
    setName('');
    setFloor('');
    setBedrooms('');
    setBathrooms('');
    setSquareFeet('');
    setMarketRent('');
    setStatusValue('available');
    setAddr1('');
    setAddr2('');
    setCity('');
    setStateVal('');
    setZip('');
    setPropertyType('');
    setYearBuilt('');
    setAvailableDate('');
    setDescription('');
    setAmenities('');
    setNotes('');
    setError(null);
    setQueuedFiles([]);
    setModalOpen(true);
  };

  const openEdit = (u: RentalUnit) => {
    setEditing(u);
    setOfficeId(u.office_id ?? '');
    setUnitNumber(u.unit_number);
    setName(u.name ?? '');
    setFloor(u.floor ?? '');
    setBedrooms(u.bedrooms != null ? String(u.bedrooms) : '');
    setBathrooms(u.bathrooms ?? '');
    setSquareFeet(u.square_feet ?? '');
    setMarketRent(u.market_rent ?? '');
    setStatusValue(u.status);
    setAddr1(u.address_line_1 ?? '');
    setAddr2(u.address_line_2 ?? '');
    setCity(u.city ?? '');
    setStateVal(u.state ?? '');
    setZip(u.zip_code ?? '');
    setPropertyType(u.property_type ?? '');
    setYearBuilt(u.year_built != null ? String(u.year_built) : '');
    setAvailableDate(u.available_date ?? '');
    setDescription(u.description ?? '');
    setAmenities(u.amenities ?? '');
    setNotes(u.notes ?? '');
    setError(null);
    setQueuedFiles([]);
    setModalOpen(true);
  };

  const save = async () => {
    if (!unitNumber.trim()) {
      setError('Unit number is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        office_id: officeId || null,
        unit_number: unitNumber.trim(),
        name: name.trim() || null,
        floor: floor.trim() || null,
        bedrooms: bedrooms ? Number(bedrooms) : null,
        bathrooms: bathrooms.trim() || null,
        square_feet: squareFeet.trim() || null,
        market_rent: marketRent.trim() || null,
        status: statusValue,
        address_line_1: addr1.trim() || null,
        address_line_2: addr2.trim() || null,
        city: city.trim() || null,
        state: stateVal.trim() || null,
        zip_code: zip.trim() || null,
        property_type: propertyType.trim() || null,
        year_built: yearBuilt ? Number(yearBuilt) : null,
        available_date: availableDate.trim() || null,
        description: description.trim() || null,
        amenities: amenities.trim() || null,
        notes: notes.trim() || null,
      };
      if (editing) {
        await leasing.updateUnit(editing.id, payload);
        addFlash({ type: 'success', content: 'Unit updated.' });
      } else {
        const res = await leasing.createUnit(payload);
        const newId = String(res.data.id);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('rental_unit', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        if (failed.length > 0) {
          addFlash({
            type: 'warning',
            content: `Unit created, but ${failed.length} attachment(s) failed: ${failed.join(', ')}.`,
          });
        } else {
          addFlash({ type: 'success', content: 'Unit created.' });
        }
      }
      setModalOpen(false);
      await load();
    } catch {
      setError('Failed to save unit.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (u: RentalUnit) => {
    if (!window.confirm(`Delete unit ${u.unit_number}?`)) return;
    try {
      await leasing.deleteUnit(u.id);
      addFlash({ type: 'success', content: 'Unit deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete unit.' });
    }
  };

  return (
    <SpaceBetween size="l">
      {occupancy && (
        <Container header={<Header variant="h3">Occupancy</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Total units</Box>
              <Box fontSize="display-l">{occupancy.total_units}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Occupied</Box>
              <Box fontSize="display-l">{occupancy.counts.occupied ?? 0}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Occupancy rate</Box>
              <Box fontSize="display-l">{(occupancy.occupancy_rate * 100).toFixed(1)}%</Box>
            </div>
          </ColumnLayout>
        </Container>
      )}

      <Table<RentalUnit>
        loading={loading}
        items={units}
        variant="container"
        header={
          <Header
            counter={`(${units.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Select
                  selectedOption={statusFilter}
                  onChange={({ detail }) => setStatusFilter(detail.selectedOption as Opt)}
                  options={[
                    { label: 'All statuses', value: '' },
                    ...UNIT_STATUSES.map((s) => ({ label: s, value: s })),
                  ]}
                />
                <Button variant="primary" onClick={openCreate}>
                  Add unit
                </Button>
              </SpaceBetween>
            }
          >
            Rental units
          </Header>
        }
        columnDefinitions={[
          { id: 'unit', header: 'Unit', cell: (u) => u.unit_number },
          { id: 'name', header: 'Name', cell: (u) => u.name ?? '—' },
          { id: 'office', header: 'Property', cell: (u) => officeLabel(u.office_id) },
          { id: 'beds', header: 'Beds', cell: (u) => u.bedrooms ?? '—' },
          { id: 'rent', header: 'Market rent', cell: (u) => fmtMoney(u.market_rent) },
          { id: 'status', header: 'Status', cell: (u) => unitBadge(u.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (u) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => openEdit(u)}>
                  Edit
                </Button>
                <Button variant="inline-link" onClick={() => remove(u)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No rental units yet.</Box>}
      />

      <EntityFormModal
        visible={modalOpen}
        onCancel={() => setModalOpen(false)}
        title={editing ? 'Edit unit' : 'Add unit'}
        size="large"
        onSubmit={save}
        submitting={saving}
        error={error}
      >
        <SpaceBetween size="m">
          <FormField label="Property">
            <Select
              selectedOption={officeOptions.find((o) => o.value === officeId) ?? officeOptions[0]}
              onChange={({ detail }) => setOfficeId(detail.selectedOption.value ?? '')}
              options={officeOptions}
              filteringType="auto"
            />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Unit number">
              <Input value={unitNumber} onChange={({ detail }) => setUnitNumber(detail.value)} />
            </FormField>
            <FormField label="Name">
              <Input value={name} onChange={({ detail }) => setName(detail.value)} />
            </FormField>
            <FormField label="Floor">
              <Input value={floor} onChange={({ detail }) => setFloor(detail.value)} />
            </FormField>
            <FormField label="Bedrooms">
              <Input
                type="number"
                value={bedrooms}
                onChange={({ detail }) => setBedrooms(detail.value)}
              />
            </FormField>
            <FormField label="Bathrooms">
              <Input
                type="number"
                value={bathrooms}
                onChange={({ detail }) => setBathrooms(detail.value)}
              />
            </FormField>
            <FormField label="Square feet">
              <Input
                type="number"
                value={squareFeet}
                onChange={({ detail }) => setSquareFeet(detail.value)}
              />
            </FormField>
            <FormField label="Market rent">
              <Input
                type="number"
                value={marketRent}
                onChange={({ detail }) => setMarketRent(detail.value)}
              />
            </FormField>
            <FormField label="Property type">
              <Input
                value={propertyType}
                onChange={({ detail }) => setPropertyType(detail.value)}
              />
            </FormField>
            <FormField label="Year built">
              <Input
                type="number"
                value={yearBuilt}
                onChange={({ detail }) => setYearBuilt(detail.value)}
              />
            </FormField>
            <FormField label="Available date">
              <Input
                type="date"
                value={availableDate}
                onChange={({ detail }) => setAvailableDate(detail.value)}
              />
            </FormField>
            <FormField label="Status">
              <Select
                selectedOption={{ label: statusValue, value: statusValue }}
                onChange={({ detail }) =>
                  setStatusValue(detail.selectedOption.value as UnitStatus)
                }
                options={UNIT_STATUSES.map((s) => ({ label: s, value: s }))}
              />
            </FormField>
          </ColumnLayout>
          <FormField label="Address line 1">
            <Input value={addr1} onChange={({ detail }) => setAddr1(detail.value)} />
          </FormField>
          <FormField label="Address line 2">
            <Input value={addr2} onChange={({ detail }) => setAddr2(detail.value)} />
          </FormField>
          <ColumnLayout columns={3}>
            <FormField label="City">
              <Input value={city} onChange={({ detail }) => setCity(detail.value)} />
            </FormField>
            <FormField label="State">
              <Input value={stateVal} onChange={({ detail }) => setStateVal(detail.value)} />
            </FormField>
            <FormField label="ZIP code">
              <Input value={zip} onChange={({ detail }) => setZip(detail.value)} />
            </FormField>
          </ColumnLayout>
          <FormField label="Description">
            <Textarea
              value={description}
              onChange={({ detail }) => setDescription(detail.value)}
            />
          </FormField>
          <FormField label="Amenities">
            <Textarea value={amenities} onChange={({ detail }) => setAmenities(detail.value)} />
          </FormField>
          <FormField label="Notes">
            <Textarea value={notes} onChange={({ detail }) => setNotes(detail.value)} />
          </FormField>
          {editing ? (
            <AttachmentsPanel
              entityType="rental_unit"
              entityId={editing.id}
              canEdit={canEditDocuments}
            />
          ) : (
            <FileUploadField files={queuedFiles} onChange={setQueuedFiles} disabled={saving} />
          )}
        </SpaceBetween>
      </EntityFormModal>
    </SpaceBetween>
  );
};

export default LeasingUnitsPage;
