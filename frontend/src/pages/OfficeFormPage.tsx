import React, { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Textarea from '@cloudscape-design/components/textarea';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Toggle from '@cloudscape-design/components/toggle';
import Checkbox from '@cloudscape-design/components/checkbox';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import Modal from '@cloudscape-design/components/modal';
import { offices as officesApi, managers as managersApi, attachments as attachmentsApi, organizations as organizationsApi, landlords as landlordsApi } from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import { EntityQuickCreateSelect } from '@/components/common/EntityQuickCreateSelect';
import { ManagerQuickCreate } from '@/components/common/QuickCreateForms';
import AddressFields, { type StructuredAddress } from '@/components/common/AddressFields';
import type { OfficeCreate, Manager, Landlord } from '@/types';

const OFFICE_TYPE_OPTIONS = [
  { label: 'Branch', value: 'Branch' },
  { label: 'Headquarters', value: 'Headquarters' },
  { label: 'HQ', value: 'HQ' },
  { label: 'Satellite', value: 'Satellite' },
  { label: 'Remote', value: 'Remote' },
  { label: 'Field', value: 'Field' },
  { label: 'Office', value: 'Office' },
  { label: 'Other', value: 'Other' },
];

// Form state mirrors OfficeCreate but keeps office_number as string for Input binding
type OfficeFormState = Omit<OfficeCreate, 'office_number' | 'region_number' | 'total_sqft' | 'usable_sqft' | 'headcount_capacity' | 'current_headcount'> & {
  office_number: string;
  region_number: string;
  total_sqft: string;
  usable_sqft: string;
  headcount_capacity: string;
  current_headcount: string;
};

const emptyForm = (): OfficeFormState => ({
  office_number: '',
  location_name: '',
  location_type: '',
  sector: '',
  region_number: '',
  address_line_1: '',
  city: '',
  state: '',
  zip_code: '',
  phone_number: '',
  fax: '',
  manager_id: undefined,
  is_active: true,
  notes: '',
  total_sqft: '',
  usable_sqft: '',
  headcount_capacity: '',
  current_headcount: '',
  space_type: '',
  owner_same_as_landlord: false,
  owner_name: '',
  owner_company: '',
  owner_email: '',
  owner_phone: '',
  owner_address_line_1: '',
  owner_address_line_2: '',
  owner_city: '',
  owner_state: '',
  owner_zip_code: '',
});

type FieldErrors = Partial<Record<keyof OfficeFormState, string>>;

const OfficeFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = Boolean(id);

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [managers, setManagers] = useState<{ label: string; value: string }[]>([]);
  const [form, setForm] = useState<OfficeFormState>(emptyForm);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);
  const [officeLandlord, setOfficeLandlord] = useState<Landlord | null>(null);
  const [allLandlords, setAllLandlords] = useState<Landlord[]>([]);
  const [selectedLandlordOption, setSelectedLandlordOption] = useState<{ label: string; value: string } | null>(null);
  const [planLimitModal, setPlanLimitModal] = useState(false);
  const [orgPlan, setOrgPlan] = useState<string>('starter');
  const [officeCount, setOfficeCount] = useState(0);
  const [planLimits] = useState({ starter: 10, pro: 50, enterprise: null as null | number });

  // Load managers for the Select
  useEffect(() => {
    managersApi
      .list()
      .then((res) =>
        setManagers(res.data.map((m: Manager) => ({ label: m.name, value: String(m.id) })))
      )
      .catch(() => {
        // non-critical — form still usable without manager list
      });
  }, []);

  // Load organization plan and office count (for new offices only)
  useEffect(() => {
    if (isEdit) return; // Skip for edit mode
    const fetchOrgAndCount = async () => {
      try {
        const orgRes = await organizationsApi.getMe();
        setOrgPlan(orgRes.data.plan || 'starter');

        // Get office count
        const officesRes = await officesApi.list({ page_size: 1 });
        setOfficeCount(officesRes.data.total || 0);
      } catch {
        // non-critical — form still usable
      }
    };
    fetchOrgAndCount();
  }, [isEdit]);

  // Load existing office when editing
  useEffect(() => {
    if (!isEdit || !id) return;
    const fetchOffice = async () => {
      try {
        const res = await officesApi.get(id);
        const o = res.data;
        setForm({
          office_number: String(o.office_number),
          location_name: o.location_name,
          location_type: o.location_type,
          sector: o.sector ?? '',
          region_number: o.region_number != null ? String(o.region_number) : '',
          address_line_1: o.address_line_1 ?? '',
          city: o.city ?? '',
          state: o.state ?? '',
          zip_code: o.zip_code ?? '',
          phone_number: o.phone_number ?? '',
          fax: o.fax ?? '',
          manager_id: o.manager_id,
          is_active: o.is_active,
          notes: o.notes ?? '',
          total_sqft: o.total_sqft != null ? String(o.total_sqft) : '',
          usable_sqft: o.usable_sqft != null ? String(o.usable_sqft) : '',
          headcount_capacity: o.headcount_capacity != null ? String(o.headcount_capacity) : '',
          current_headcount: o.current_headcount != null ? String(o.current_headcount) : '',
          space_type: o.space_type ?? '',
          owner_same_as_landlord: o.owner_same_as_landlord ?? false,
          owner_name: o.owner_name ?? '',
          owner_company: o.owner_company ?? '',
          owner_email: o.owner_email ?? '',
          owner_phone: o.owner_phone ?? '',
          owner_address_line_1: o.owner_address_line_1 ?? '',
          owner_address_line_2: o.owner_address_line_2 ?? '',
          owner_city: o.owner_city ?? '',
          owner_state: o.owner_state ?? '',
          owner_zip_code: o.owner_zip_code ?? '',
        });
      } catch {
        setError('Failed to load office data.');
      } finally {
        setLoading(false);
      }
    };
    fetchOffice();
  }, [id, isEdit]);

  // Load the office's primary landlord so the "same as landlord" checkbox can mirror its details.
  useEffect(() => {
    if (!isEdit || !id) return;
    landlordsApi
      .list({ office_id: id, page_size: 1 })
      .then((res) => setOfficeLandlord(res.data.items?.[0] ?? null))
      .catch(() => setOfficeLandlord(null));
  }, [id, isEdit]);

  // Load all of the organization's landlords so a landlord can be picked (and
  // associated with the office) even when the office has no landlord yet —
  // e.g. when creating a brand-new office.
  useEffect(() => {
    if (isEdit && officeLandlord) return; // office already has a landlord to mirror
    landlordsApi
      .list({ page_size: 500, sort_by: 'landlord_company' })
      .then((res) => setAllLandlords(res.data.items ?? []))
      .catch(() => setAllLandlords([]));
  }, [isEdit, officeLandlord]);

  const landlordOptions = useMemo(
    () =>
      allLandlords.map((l) => ({
        label: l.landlord_company || l.office_name || l.contact_name || l.ern || 'Unnamed landlord',
        value: l.id,
      })),
    [allLandlords],
  );

  // Map a landlord's contact/address details onto the owner form fields.
  const ownerFieldsFromLandlord = (l: Landlord) => ({
    owner_name: l.contact_name ?? '',
    owner_company: l.landlord_company ?? l.office_name ?? '',
    owner_email: l.contact_email ?? '',
    owner_phone: l.contact_phone ?? '',
    owner_address_line_1: l.address_line_1 ?? '',
    owner_address_line_2: l.address_line_2 ?? '',
    owner_city: l.city ?? '',
    owner_state: l.state ?? '',
    owner_zip_code: l.zip_code ?? '',
  });

  const handleSameAsLandlordToggle = (checked: boolean) => {
    if (!checked) {
      setSelectedLandlordOption(null);
    }
    setForm((prev) => {
      if (checked && officeLandlord) {
        return { ...prev, owner_same_as_landlord: true, ...ownerFieldsFromLandlord(officeLandlord) };
      }
      return { ...prev, owner_same_as_landlord: checked };
    });
  };

  const handleLandlordSelect = (option: { label: string; value: string } | null) => {
    setSelectedLandlordOption(option);
    if (!option) return;
    const landlord = allLandlords.find((l) => l.id === option.value);
    if (landlord) {
      setForm((prev) => ({ ...prev, owner_same_as_landlord: true, ...ownerFieldsFromLandlord(landlord) }));
    }
  };

  const setField = <K extends keyof OfficeFormState>(key: K, value: OfficeFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (fieldErrors[key]) {
      setFieldErrors((prev) => ({ ...prev, [key]: undefined }));
    }
  };

  const validate = (): boolean => {
    const errors: FieldErrors = {};
    if (!form.office_number.trim()) errors.office_number = 'Office number is required.';
    else if (isNaN(parseInt(form.office_number.trim(), 10))) errors.office_number = 'Office number must be a number.';
    if (!form.location_name.trim()) errors.location_name = 'Location name is required.';
    if (!form.location_type) errors.location_type = 'Office type is required.';
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;

    // Check plan limit for new offices
    if (!isEdit) {
      const limit = planLimits[orgPlan as keyof typeof planLimits];
      if (limit !== null && officeCount >= limit) {
        setPlanLimitModal(true);
        return;
      }
    }

    setSaving(true);
    setError(null);
    try {
      const payload: OfficeCreate = {
        office_number: parseInt(form.office_number.trim(), 10),
        location_name: form.location_name.trim(),
        location_type: form.location_type,
        sector: form.sector?.trim() || undefined,
        region_number: form.region_number?.trim() ? parseInt(form.region_number.trim(), 10) : undefined,
        address_line_1: form.address_line_1?.trim() || undefined,
        city: form.city?.trim() || undefined,
        state: form.state?.trim() || undefined,
        zip_code: form.zip_code?.trim() || undefined,
        phone_number: form.phone_number?.trim() || undefined,
        fax: form.fax?.trim() || undefined,
        manager_id: form.manager_id,
        is_active: form.is_active,
        notes: form.notes?.trim() || undefined,
        total_sqft: form.total_sqft?.trim() ? parseFloat(form.total_sqft) : undefined,
        usable_sqft: form.usable_sqft?.trim() ? parseFloat(form.usable_sqft) : undefined,
        headcount_capacity: form.headcount_capacity?.trim() ? parseInt(form.headcount_capacity, 10) : undefined,
        current_headcount: form.current_headcount?.trim() ? parseInt(form.current_headcount, 10) : undefined,
        space_type: form.space_type?.trim() || undefined,
        owner_same_as_landlord: form.owner_same_as_landlord ?? false,
        owner_name: form.owner_name?.trim() || undefined,
        owner_company: form.owner_company?.trim() || undefined,
        owner_email: form.owner_email?.trim() || undefined,
        owner_phone: form.owner_phone?.trim() || undefined,
        owner_address_line_1: form.owner_address_line_1?.trim() || undefined,
        owner_address_line_2: form.owner_address_line_2?.trim() || undefined,
        owner_city: form.owner_city?.trim() || undefined,
        owner_state: form.owner_state?.trim() || undefined,
        owner_zip_code: form.owner_zip_code?.trim() || undefined,
      };

      if (isEdit && id) {
        await officesApi.update(id, payload);
        navigate(`/offices/${id}`);
      } else {
        const res = await officesApi.create(payload);
        const newId = String(res.data.id);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('office', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        // Associate the selected landlord with the newly created office (the
        // office didn't exist yet, so this couldn't be done beforehand).
        if (form.owner_same_as_landlord && selectedLandlordOption) {
          const landlord = allLandlords.find((l) => l.id === selectedLandlordOption.value);
          if (landlord) {
            const existingIds = (landlord.owned_offices ?? []).map((o) => o.id);
            const officeIds = Array.from(new Set([...existingIds, newId]));
            try {
              await landlordsApi.update(landlord.id, { office_ids: officeIds });
            } catch {
              setError((prev) =>
                prev ?? 'Office created, but failed to associate the selected landlord. Link them from the office page.',
              );
            }
          }
        }
        if (failed.length > 0) {
          setError(
            `Office created, but ${failed.length} attachment(s) failed: ${failed.join(', ')}. Re-upload from the office page.`,
          );
        }
        navigate(`/offices/${newId}`);
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || (isEdit ? 'Failed to update office.' : 'Failed to create office.'));
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (isEdit && id) {
      navigate(`/offices/${id}`);
    } else {
      navigate('/offices');
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  const selectedTypeOption = form.location_type
    ? OFFICE_TYPE_OPTIONS.find((o) => o.value === form.location_type) ??
      { label: form.location_type, value: form.location_type }
    : null;

  const selectedManagerOption =
    form.manager_id != null
      ? managers.find((m) => m.value === String(form.manager_id)) ?? null
      : null;

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Offices', href: '/offices' },
              ...(isEdit && id
                ? [
                    { text: form.location_name || 'Office', href: `/offices/${id}` },
                    { text: 'Edit', href: '#' },
                  ]
                : [{ text: 'New Office', href: '#' }]),
            ]}
            onFollow={(e) => {
              e.preventDefault();
              if (e.detail.href !== '#') navigate(e.detail.href);
            }}
          />
          <Header variant="h1">
            {isEdit ? `Edit ${form.location_name || 'Office'}` : 'Create Office'}
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={handleCancel}>
                Cancel
              </Button>
              <Button variant="primary" loading={saving} onClick={handleSubmit}>
                {isEdit ? 'Save Changes' : 'Create Office'}
              </Button>
            </SpaceBetween>
          }
        >
          <SpaceBetween size="l">
            {/* ── Basic Information ──────────────────────────────────────────── */}
            <Container header={<Header variant="h2">Basic Information</Header>}>
              <SpaceBetween size="m">
                <FormField
                  label="Office Number"
                  constraintText="Required"
                  errorText={fieldErrors.office_number}
                >
                  <Input
                    value={form.office_number}
                    onChange={({ detail }) => setField('office_number', detail.value)}
                    placeholder="e.g., 001"
                  />
                </FormField>

                <FormField
                  label="Location Name"
                  constraintText="Required"
                  errorText={fieldErrors.location_name}
                  stretch
                >
                  <Input
                    value={form.location_name}
                    onChange={({ detail }) => setField('location_name', detail.value)}
                    placeholder="e.g., Downtown Branch"
                  />
                </FormField>

                <FormField
                  label="Office Type"
                  constraintText="Required"
                  errorText={fieldErrors.location_type}
                >
                  <Select
                    selectedOption={selectedTypeOption}
                    onChange={({ detail }) =>
                      setField('location_type', detail.selectedOption?.value ?? '')
                    }
                    options={OFFICE_TYPE_OPTIONS}
                    placeholder="Select type"
                  />
                </FormField>

                <FormField label="Sector">
                  <Input
                    value={form.sector ?? ''}
                    onChange={({ detail }) => setField('sector', detail.value)}
                    placeholder="e.g., Commercial"
                  />
                </FormField>

                <FormField label="Region">
                  <Input
                    value={form.region_number ?? ''}
                    onChange={({ detail }) => setField('region_number', detail.value)}
                    placeholder="e.g., 1"
                    type="number"
                  />
                </FormField>

                <FormField label="Manager">
                  <EntityQuickCreateSelect
                    selectedOption={selectedManagerOption}
                    onChange={(opt) =>
                      setField('manager_id', opt?.value ? opt.value : undefined)
                    }
                    options={[{ label: '— None —', value: '' }, ...managers]}
                    placeholder="Select a manager"
                    quickCreate={{
                      label: '+ Add new manager…',
                      render: ({ visible, onClose, onCreated }) => (
                        <ManagerQuickCreate
                          visible={visible}
                          onClose={onClose}
                          onCreated={onCreated}
                        />
                      ),
                    }}
                  />
                </FormField>

                <FormField label="Active Status">
                  <Toggle
                    checked={form.is_active ?? true}
                    onChange={({ detail }) => setField('is_active', detail.checked)}
                  >
                    {form.is_active ? 'Active' : 'Inactive'}
                  </Toggle>
                </FormField>
              </SpaceBetween>
            </Container>

            {/* ── Address ────────────────────────────────────────────────────── */}
            <Container header={<Header variant="h2">Address</Header>}>
              <AddressFields
                value={{
                  address_line_1: form.address_line_1 ?? undefined,
                  address_line_2: form.address_line_2 ?? undefined,
                  city: form.city ?? undefined,
                  state: form.state ?? undefined,
                  zip_code: form.zip_code ?? undefined,
                }}
                onChange={(addr: StructuredAddress) => {
                  setForm((prev) => ({
                    ...prev,
                    address_line_1: addr.address_line_1 ?? '',
                    address_line_2: addr.address_line_2 ?? '',
                    city: addr.city ?? '',
                    state: addr.state ?? '',
                    zip_code: addr.zip_code ?? '',
                  }));
                }}
                disabled={saving}
              />
            </Container>

            {/* ── Contact ────────────────────────────────────────────────────── */}
            <Container header={<Header variant="h2">Contact</Header>}>
              <SpaceBetween direction="horizontal" size="l">
                <FormField label="Phone">
                  <Input
                    value={form.phone_number ?? ''}
                    onChange={({ detail }) => setField('phone_number', detail.value)}
                    placeholder="(555) 555-5555"
                    type="tel"
                  />
                </FormField>
                <FormField label="Fax">
                  <Input
                    value={form.fax ?? ''}
                    onChange={({ detail }) => setField('fax', detail.value)}
                    placeholder="(555) 555-5556"
                    type="tel"
                  />
                </FormField>
              </SpaceBetween>
            </Container>

            {/* ── Notes ──────────────────────────────────────────────────────── */}
            <Container header={<Header variant="h2">Notes</Header>}>
              <FormField label="Notes">
                <Textarea
                  value={form.notes ?? ''}
                  onChange={({ detail }) => setField('notes', detail.value)}
                  placeholder="Additional notes..."
                  rows={4}
                />
              </FormField>
            </Container>

            {/* ── Space & Occupancy ───────────────────────────────────────── */}
            <Container header={<Header variant="h2">Space &amp; Occupancy</Header>}>
              <SpaceBetween size="m">
                <SpaceBetween direction="horizontal" size="l">
                  <FormField label="Total Sq Ft">
                    <Input
                      value={form.total_sqft ?? ''}
                      onChange={({ detail }) => setField('total_sqft', detail.value)}
                      placeholder="e.g., 4500"
                      type="number"
                    />
                  </FormField>
                  <FormField label="Usable Sq Ft">
                    <Input
                      value={form.usable_sqft ?? ''}
                      onChange={({ detail }) => setField('usable_sqft', detail.value)}
                      placeholder="e.g., 3800"
                      type="number"
                    />
                  </FormField>
                </SpaceBetween>
                <SpaceBetween direction="horizontal" size="l">
                  <FormField label="Headcount Capacity">
                    <Input
                      value={form.headcount_capacity ?? ''}
                      onChange={({ detail }) => setField('headcount_capacity', detail.value)}
                      placeholder="e.g., 50"
                      type="number"
                    />
                  </FormField>
                  <FormField label="Current Headcount">
                    <Input
                      value={form.current_headcount ?? ''}
                      onChange={({ detail }) => setField('current_headcount', detail.value)}
                      placeholder="e.g., 42"
                      type="number"
                    />
                  </FormField>
                </SpaceBetween>
                <FormField label="Space Type">
                  <Select
                    selectedOption={
                      form.space_type
                        ? { label: form.space_type, value: form.space_type }
                        : null
                    }
                    onChange={({ detail }) => setField('space_type', detail.selectedOption?.value ?? '')}
                    options={[
                      { label: '— None —', value: '' },
                      { label: 'Open Floor Plan', value: 'open_floor_plan' },
                      { label: 'Private Offices', value: 'private_offices' },
                      { label: 'Mixed / Hybrid', value: 'hybrid' },
                      { label: 'Conference / Meeting', value: 'conference' },
                      { label: 'Hoteling', value: 'hoteling' },
                    ]}
                    placeholder="Select space type"
                  />
                </FormField>
              </SpaceBetween>
            </Container>

            {/* ── Owners (the legal property owner may differ from the landlord) ── */}
            <Container
              header={
                <Header
                  variant="h2"
                  description="The property owner may be a different party than the landlord."
                >
                  Owners
                </Header>
              }
            >
              <SpaceBetween size="m">
                <Checkbox
                  checked={form.owner_same_as_landlord ?? false}
                  onChange={({ detail }) => handleSameAsLandlordToggle(detail.checked)}
                  description={
                    officeLandlord
                      ? 'Populates the owner fields from this office\u2019s landlord.'
                      : 'Select a landlord below to copy their details and associate them with this office.'
                  }
                >
                  Landlord is same as owner
                </Checkbox>
                {form.owner_same_as_landlord && !officeLandlord && (
                  <FormField label="Landlord" description="Pick the landlord this office's owner details should mirror.">
                    <Select
                      selectedOption={selectedLandlordOption}
                      onChange={({ detail }) => handleLandlordSelect(detail.selectedOption as { label: string; value: string })}
                      options={landlordOptions}
                      placeholder="Select a landlord"
                      filteringType="auto"
                      empty="No landlords found. Create one from the Landlords page first."
                    />
                  </FormField>
                )}
                <SpaceBetween direction="horizontal" size="l">
                  <FormField label="Owner Name">
                    <Input
                      value={form.owner_name ?? ''}
                      onChange={({ detail }) => setField('owner_name', detail.value)}
                      disabled={form.owner_same_as_landlord}
                    />
                  </FormField>
                  <FormField label="Owner Company">
                    <Input
                      value={form.owner_company ?? ''}
                      onChange={({ detail }) => setField('owner_company', detail.value)}
                      disabled={form.owner_same_as_landlord}
                    />
                  </FormField>
                </SpaceBetween>
                <SpaceBetween direction="horizontal" size="l">
                  <FormField label="Owner Email">
                    <Input
                      type="email"
                      value={form.owner_email ?? ''}
                      onChange={({ detail }) => setField('owner_email', detail.value)}
                      disabled={form.owner_same_as_landlord}
                    />
                  </FormField>
                  <FormField label="Owner Phone">
                    <Input
                      value={form.owner_phone ?? ''}
                      onChange={({ detail }) => setField('owner_phone', detail.value)}
                      disabled={form.owner_same_as_landlord}
                    />
                  </FormField>
                </SpaceBetween>
                <AddressFields
                  value={{
                    address_line_1: form.owner_address_line_1 ?? '',
                    address_line_2: form.owner_address_line_2 ?? '',
                    city: form.owner_city ?? '',
                    state: form.owner_state ?? '',
                    zip_code: form.owner_zip_code ?? '',
                  }}
                  onChange={(addr: StructuredAddress) =>
                    setForm((prev) => ({
                      ...prev,
                      owner_address_line_1: addr.address_line_1,
                      owner_address_line_2: addr.address_line_2,
                      owner_city: addr.city,
                      owner_state: addr.state,
                      owner_zip_code: addr.zip_code,
                    }))
                  }
                  disabled={form.owner_same_as_landlord}
                />
              </SpaceBetween>
            </Container>

            {/* ── Attachments (create only — manage from detail page when editing) ── */}
            {!isEdit && (
              <Container
                header={
                  <Header
                    variant="h2"
                    description="Files selected here will be uploaded after the office is created."
                  >
                    Attachments
                  </Header>
                }
              >
                <FileQueueField files={queuedFiles} onChange={setQueuedFiles} disabled={saving} />
              </Container>
            )}
          </SpaceBetween>
        </Form>
      </SpaceBetween>
      <Modal
        onDismiss={() => setPlanLimitModal(false)}
        visible={planLimitModal}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="primary" onClick={() => setPlanLimitModal(false)}>
                Close
              </Button>
            </SpaceBetween>
          </Box>
        }
        header="Office Limit Reached"
      >
        <SpaceBetween size="m">
          <Box>
            You have reached the office limit for your <strong>{orgPlan}</strong> plan ({planLimits[orgPlan as keyof typeof planLimits]} offices).
          </Box>
          <Box>
            To add more offices, please upgrade your plan:
          </Box>
          <Box>
            <ul>
              <li><strong>Starter:</strong> 10 offices</li>
              <li><strong>Pro:</strong> 50 offices</li>
              <li><strong>Enterprise:</strong> Unlimited offices</li>
            </ul>
          </Box>
          <Box>
            Contact support or visit your billing page to upgrade your plan.
          </Box>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default OfficeFormPage;
