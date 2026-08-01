import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useUnsavedChangesWarning from '@/hooks/useUnsavedChangesWarning';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Wizard from '@cloudscape-design/components/wizard';
import Container from '@cloudscape-design/components/container';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Textarea from '@cloudscape-design/components/textarea';
import Toggle from '@cloudscape-design/components/toggle';
import Checkbox from '@cloudscape-design/components/checkbox';
import SpaceBetween from '@cloudscape-design/components/space-between';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import {
  offices as officesApi,
  managers as managersApi,
  attachments as attachmentsApi,
  landlords as landlordsApi,
  gl as glApi,
} from '@/api';
import { EntityQuickCreateSelect } from '@/components/common/EntityQuickCreateSelect';
import {
  ManagerQuickCreate,
  LandlordQuickCreate,
  type QuickCreateOption,
} from '@/components/common/QuickCreateForms';
import AddressFields, { type StructuredAddress } from '@/components/common/AddressFields';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import AIDocumentClassify from '@/components/common/AIDocumentClassify';
import { wizardI18nStrings } from '@/components/common/wizardI18n';
import type { OfficeCreate, Manager } from '@/types';

const OFFICE_TYPE_OPTIONS: QuickCreateOption[] = [
  { label: 'Branch', value: 'Branch' },
  { label: 'Headquarters', value: 'Headquarters' },
  { label: 'HQ', value: 'HQ' },
  { label: 'Satellite', value: 'Satellite' },
  { label: 'Remote', value: 'Remote' },
  { label: 'Field', value: 'Field' },
  { label: 'Office', value: 'Office' },
  { label: 'Other', value: 'Other' },
];

interface OwnerAddress {
  owner_address_line_1: string;
  owner_address_line_2: string;
  owner_city: string;
  owner_state: string;
  owner_zip_code: string;
}

const OfficeWizardPage: React.FC = () => {
  const navigate = useNavigate();

  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);

  // Option lists
  const [managerOptions, setManagerOptions] = useState<QuickCreateOption[]>([]);
  const [glOptions, setGlOptions] = useState<QuickCreateOption[]>([]);
  const [landlordOptions, setLandlordOptions] = useState<QuickCreateOption[]>([]);

  // Step 1 — basics
  const [officeNumber, setOfficeNumber] = useState('');
  const [locationName, setLocationName] = useState('');

  // Any progress past the first step, or a typed name, is work worth protecting.
  useUnsavedChangesWarning(
    !saving && (activeStepIndex > 0 || officeNumber.trim() !== '' || locationName.trim() !== ''),
  );
  const [locationType, setLocationType] = useState<QuickCreateOption | null>(null);
  const [sector, setSector] = useState('');
  const [regionNumber, setRegionNumber] = useState('');
  const [isActive, setIsActive] = useState(true);

  // Step 2 — address & contact
  const [address, setAddress] = useState<StructuredAddress>({});
  const [phoneNumber, setPhoneNumber] = useState('');
  const [fax, setFax] = useState('');
  const [email, setEmail] = useState('');

  // Step 3 — space & capacity
  const [totalSqft, setTotalSqft] = useState('');
  const [usableSqft, setUsableSqft] = useState('');
  const [headcountCapacity, setHeadcountCapacity] = useState('');
  const [currentHeadcount, setCurrentHeadcount] = useState('');
  const [spaceType, setSpaceType] = useState('');

  // Step 4 — manager, GL, notes
  const [manager, setManager] = useState<QuickCreateOption | null>(null);
  const [glAccount, setGlAccount] = useState<QuickCreateOption | null>(null);
  const [notes, setNotes] = useState('');

  // Step 5 — landlord & ownership
  const [landlord, setLandlord] = useState<QuickCreateOption | null>(null);
  const [ownerSameAsLandlord, setOwnerSameAsLandlord] = useState(false);
  const [ownerName, setOwnerName] = useState('');
  const [ownerCompany, setOwnerCompany] = useState('');
  const [ownerEmail, setOwnerEmail] = useState('');
  const [ownerPhone, setOwnerPhone] = useState('');
  const [ownerAddress, setOwnerAddress] = useState<OwnerAddress>({
    owner_address_line_1: '',
    owner_address_line_2: '',
    owner_city: '',
    owner_state: '',
    owner_zip_code: '',
  });

  // Per-field validation errors (basics step only requires fields)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    managersApi
      .list()
      .then((res) =>
        setManagerOptions(res.data.map((m: Manager) => ({ label: m.name, value: String(m.id) }))),
      )
      .catch(() => undefined);
    glApi
      .accountOptions()
      .then((res) =>
        setGlOptions(res.data.map((a) => ({ label: `${a.code} — ${a.name}`, value: String(a.id) }))),
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

  const officeNumberInt = officeNumber.trim() === '' ? NaN : parseInt(officeNumber.trim(), 10);

  const validateBasics = (): boolean => {
    const errs: Record<string, string> = {};
    if (officeNumber.trim() === '') {
      errs.office_number = 'Office number is required.';
    } else if (Number.isNaN(officeNumberInt)) {
      errs.office_number = 'Office number must be a whole number.';
    }
    if (locationName.trim() === '') errs.location_name = 'Location name is required.';
    if (!locationType) errs.location_type = 'Office type is required.';
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const landlordName = landlord?.label ?? '';

  // When "owner same as landlord" is toggled on, prefill owner company from the
  // selected landlord for convenience.
  useEffect(() => {
    if (ownerSameAsLandlord && landlordName && !ownerCompany.trim()) {
      setOwnerCompany(landlordName);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownerSameAsLandlord]);

  const buildPayload = (): OfficeCreate => ({
    office_number: officeNumberInt,
    location_name: locationName.trim(),
    location_type: locationType?.value ?? '',
    sector: sector.trim() || undefined,
    region_number: regionNumber.trim() ? parseInt(regionNumber.trim(), 10) : undefined,
    is_active: isActive,
    address_line_1: address.address_line_1?.trim() || undefined,
    address_line_2: address.address_line_2?.trim() || undefined,
    city: address.city?.trim() || undefined,
    state: address.state?.trim() || undefined,
    zip_code: address.zip_code?.trim() || undefined,
    phone_number: phoneNumber.trim() || undefined,
    fax: fax.trim() || undefined,
    email: email.trim() || undefined,
    total_sqft: totalSqft.trim() ? parseFloat(totalSqft) : undefined,
    usable_sqft: usableSqft.trim() ? parseFloat(usableSqft) : undefined,
    headcount_capacity: headcountCapacity.trim() ? parseInt(headcountCapacity, 10) : undefined,
    current_headcount: currentHeadcount.trim() ? parseInt(currentHeadcount, 10) : undefined,
    space_type: spaceType.trim() || undefined,
    manager_id: manager?.value,
    gl_account_id: glAccount?.value ?? undefined,
    notes: notes.trim() || undefined,
    owner_same_as_landlord: ownerSameAsLandlord,
    owner_name: ownerName.trim() || undefined,
    owner_company: ownerCompany.trim() || undefined,
    owner_email: ownerEmail.trim() || undefined,
    owner_phone: ownerPhone.trim() || undefined,
    owner_address_line_1: ownerAddress.owner_address_line_1.trim() || undefined,
    owner_address_line_2: ownerAddress.owner_address_line_2.trim() || undefined,
    owner_city: ownerAddress.owner_city.trim() || undefined,
    owner_state: ownerAddress.owner_state.trim() || undefined,
    owner_zip_code: ownerAddress.owner_zip_code.trim() || undefined,
  });

  const handleSubmit = async () => {
    if (!validateBasics()) {
      setActiveStepIndex(0);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await officesApi.create(buildPayload());
      const newId = String(res.data.id);

      // Associate the selected landlord with the newly-created office. Fetch the
      // landlord fresh so we don't clobber its existing office associations.
      if (landlord) {
        try {
          const fresh = await landlordsApi.get(landlord.value);
          const existingIds = (fresh.data.owned_offices ?? []).map((o) => o.id);
          const officeIds = Array.from(new Set([...existingIds, newId]));
          await landlordsApi.update(landlord.value, { office_ids: officeIds });
        } catch {
          setError(
            'Office created, but linking the landlord failed. You can link them from the office page.',
          );
        }
      }
      for (const qf of queuedFiles) {
        try {
          await attachmentsApi.upload('office', newId, qf.file);
        } catch {
          // best-effort: ignore individual attachment upload failures
        }
      }
      navigate(`/offices/${newId}`);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to create office.');
      setSaving(false);
    }
  };

  // Queue a document that was identified by the AI classifier so it is
  // uploaded when the office is created. Dedupe by name+size.
  const queueClassifiedFile = (file: File) => {
    setQueuedFiles((prev) => {
      if (prev.some((qf) => qf.file.name === file.name && qf.file.size === file.size)) {
        return prev;
      }
      return [...prev, { file, id: `${file.name}-${file.size}-${Date.now()}` }];
    });
  };

  const ownerAddressStructured: StructuredAddress = {
    address_line_1: ownerAddress.owner_address_line_1,
    address_line_2: ownerAddress.owner_address_line_2,
    city: ownerAddress.owner_city,
    state: ownerAddress.owner_state,
    zip_code: ownerAddress.owner_zip_code,
  };

  const steps = useMemo(
    () => [
      {
        title: 'Office basics',
        description: 'Core identifiers for the new office.',
        content: (
          <Container header={<Header variant="h2">Office basics</Header>}>
            <SpaceBetween size="l">
              <ColumnLayout columns={2}>
                <FormField label="Office number" constraintText="Required" errorText={fieldErrors.office_number}>
                  <Input
                    value={officeNumber}
                    onChange={({ detail }) => setOfficeNumber(detail.value)}
                    type="number"
                    inputMode="numeric"
                    placeholder="e.g., 101"
                  />
                </FormField>
                <FormField label="Office type" constraintText="Required" errorText={fieldErrors.location_type}>
                  <Select
                    selectedOption={locationType}
                    onChange={({ detail }) => setLocationType(detail.selectedOption as QuickCreateOption)}
                    options={OFFICE_TYPE_OPTIONS}
                    placeholder="Select type"
                  />
                </FormField>
              </ColumnLayout>
              <FormField label="Location name" constraintText="Required" errorText={fieldErrors.location_name}>
                <Input
                  value={locationName}
                  onChange={({ detail }) => setLocationName(detail.value)}
                  placeholder="e.g., Downtown Branch"
                />
              </FormField>
              <ColumnLayout columns={2}>
                <FormField label="Sector">
                  <Input value={sector} onChange={({ detail }) => setSector(detail.value)} placeholder="e.g., Retail" />
                </FormField>
                <FormField label="Region number">
                  <Input
                    value={regionNumber}
                    onChange={({ detail }) => setRegionNumber(detail.value)}
                    type="number"
                    inputMode="numeric"
                    placeholder="e.g., 5"
                  />
                </FormField>
              </ColumnLayout>
              <FormField label="Status">
                <Toggle checked={isActive} onChange={({ detail }) => setIsActive(detail.checked)}>
                  {isActive ? 'Active' : 'Inactive'}
                </Toggle>
              </FormField>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Address & contact',
        description: 'Where is the office and how do you reach it?',
        isOptional: true,
        content: (
          <Container header={<Header variant="h2">Address & contact</Header>}>
            <SpaceBetween size="l">
              <AddressFields value={address} onChange={setAddress} />
              <ColumnLayout columns={3}>
                <FormField label="Phone">
                  <Input value={phoneNumber} onChange={({ detail }) => setPhoneNumber(detail.value)} placeholder="Phone number" />
                </FormField>
                <FormField label="Fax">
                  <Input value={fax} onChange={({ detail }) => setFax(detail.value)} placeholder="Fax number" />
                </FormField>
                <FormField label="Email">
                  <Input value={email} onChange={({ detail }) => setEmail(detail.value)} type="email" placeholder="Email address" />
                </FormField>
              </ColumnLayout>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Space & capacity',
        description: 'Square footage and headcount for this location.',
        isOptional: true,
        content: (
          <Container header={<Header variant="h2">Space & capacity</Header>}>
            <SpaceBetween size="l">
              <ColumnLayout columns={2}>
                <FormField label="Total sq ft">
                  <Input value={totalSqft} onChange={({ detail }) => setTotalSqft(detail.value)} type="number" inputMode="numeric" placeholder="e.g., 12000" />
                </FormField>
                <FormField label="Usable sq ft">
                  <Input value={usableSqft} onChange={({ detail }) => setUsableSqft(detail.value)} type="number" inputMode="numeric" placeholder="e.g., 10500" />
                </FormField>
                <FormField label="Headcount capacity">
                  <Input value={headcountCapacity} onChange={({ detail }) => setHeadcountCapacity(detail.value)} type="number" inputMode="numeric" placeholder="e.g., 80" />
                </FormField>
                <FormField label="Current headcount">
                  <Input value={currentHeadcount} onChange={({ detail }) => setCurrentHeadcount(detail.value)} type="number" inputMode="numeric" placeholder="e.g., 62" />
                </FormField>
              </ColumnLayout>
              <FormField label="Space type">
                <Input value={spaceType} onChange={({ detail }) => setSpaceType(detail.value)} placeholder="e.g., Open plan, Suite" />
              </FormField>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Management & accounting',
        description: 'Assign a manager, GL account, and notes.',
        isOptional: true,
        content: (
          <Container header={<Header variant="h2">Management & accounting</Header>}>
            <SpaceBetween size="l">
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
              <FormField label="GL account" description="Chart-of-accounts code this office rolls up to.">
                <Select
                  selectedOption={glAccount}
                  onChange={({ detail }) => setGlAccount((detail.selectedOption as QuickCreateOption) ?? null)}
                  options={glOptions}
                  placeholder="Select GL account"
                  filteringType="auto"
                  empty="No GL accounts"
                />
              </FormField>
              <FormField label="Notes">
                <Textarea value={notes} onChange={({ detail }) => setNotes(detail.value)} placeholder="Optional notes about this office" />
              </FormField>
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Landlord & ownership',
        description: 'Link a landlord and capture ownership details.',
        isOptional: true,
        content: (
          <Container header={<Header variant="h2">Landlord & ownership</Header>}>
            <SpaceBetween size="l">
              <FormField
                label="Landlord"
                description="Select an existing landlord or create a new one inline. The office will be linked to them."
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
              <Checkbox
                checked={ownerSameAsLandlord}
                onChange={({ detail }) => setOwnerSameAsLandlord(detail.checked)}
              >
                The building owner is the same as the landlord
              </Checkbox>
              <ColumnLayout columns={2}>
                <FormField label="Owner name">
                  <Input value={ownerName} onChange={({ detail }) => setOwnerName(detail.value)} placeholder="Owner contact name" />
                </FormField>
                <FormField label="Owner company">
                  <Input value={ownerCompany} onChange={({ detail }) => setOwnerCompany(detail.value)} placeholder="Owning entity" />
                </FormField>
                <FormField label="Owner email">
                  <Input value={ownerEmail} onChange={({ detail }) => setOwnerEmail(detail.value)} type="email" placeholder="Email address" />
                </FormField>
                <FormField label="Owner phone">
                  <Input value={ownerPhone} onChange={({ detail }) => setOwnerPhone(detail.value)} placeholder="Phone number" />
                </FormField>
              </ColumnLayout>
              <Box variant="h4">Owner address</Box>
              <AddressFields
                value={ownerAddressStructured}
                onChange={(next) =>
                  setOwnerAddress({
                    owner_address_line_1: next.address_line_1 ?? '',
                    owner_address_line_2: next.address_line_2 ?? '',
                    owner_city: next.city ?? '',
                    owner_state: next.state ?? '',
                    owner_zip_code: next.zip_code ?? '',
                  })
                }
              />
            </SpaceBetween>
          </Container>
        ),
      },
      {
        title: 'Documents',
        description: 'Attach lease, floor plan, or other office documents (optional).',
        isOptional: true,
        content: (
          <SpaceBetween size="l">
            <AIDocumentClassify
              title="Identify a document with AI"
              description="Upload a document (e.g. the current lease or a certificate) and AI will detect what it is, then queue it for this office."
              dropzoneText="Drop an office document here to identify it"
              onFileClassified={queueClassifiedFile}
            />
            <Container header={<Header variant="h2">Documents</Header>}>
              <SpaceBetween size="l">
                <Box variant="p" color="text-body-secondary">
                  Upload any documents related to this office, such as the current lease,
                  floor plans, or certificates. Files are uploaded after the office is created.
                </Box>
                <FileQueueField files={queuedFiles} onChange={setQueuedFiles} disabled={saving} />
              </SpaceBetween>
            </Container>
          </SpaceBetween>
        ),
      },      {
        title: 'Review & create',
        description: 'Confirm the details before creating the office.',
        content: (
          <Container header={<Header variant="h2">Review</Header>}>
            <SpaceBetween size="l">
              {error && <Alert type="error">{error}</Alert>}
              <ColumnLayout columns={2} variant="text-grid">
                <div>
                  <Box variant="awsui-key-label">Office number</Box>
                  <div>{officeNumber || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Office type</Box>
                  <div>{locationType?.label || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Location name</Box>
                  <div>{locationName || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Status</Box>
                  <div>{isActive ? 'Active' : 'Inactive'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Manager</Box>
                  <div>{manager?.label || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">GL account</Box>
                  <div>{glAccount?.label || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">Landlord</Box>
                  <div>{landlord?.label || '—'}</div>
                </div>
                <div>
                  <Box variant="awsui-key-label">City / State</Box>
                  <div>{[address.city, address.state].filter(Boolean).join(', ') || '—'}</div>
                </div>
              </ColumnLayout>
            </SpaceBetween>
          </Container>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      fieldErrors, officeNumber, locationType, locationName, sector, regionNumber, isActive,
      address, phoneNumber, fax, email, totalSqft, usableSqft, headcountCapacity, currentHeadcount,
      spaceType, managerOptions, manager, glOptions, glAccount, notes, landlordOptions, landlord,
      ownerSameAsLandlord, ownerName, ownerCompany, ownerEmail, ownerPhone, ownerAddress, error,
      queuedFiles, saving,
    ],
  );

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Offices', href: '/offices' },
              { text: 'New office wizard', href: '#' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              if (e.detail.href === '/offices') navigate('/offices');
            }}
          />
          <Header variant="h1" description="A guided walkthrough to onboard a new office with all details.">
            New office wizard
          </Header>
        </SpaceBetween>
      }
    >
      <Wizard
        steps={steps}
        activeStepIndex={activeStepIndex}
        i18nStrings={wizardI18nStrings('Create office')}
        isLoadingNextStep={saving}
        onNavigate={({ detail }) => {
          // Validate the basics step before moving forward off of it.
          if (activeStepIndex === 0 && detail.requestedStepIndex > 0 && !validateBasics()) {
            return;
          }
          setActiveStepIndex(detail.requestedStepIndex);
        }}
        onCancel={() => navigate('/offices')}
        onSubmit={handleSubmit}
      />
    </ContentLayout>
  );
};

export default OfficeWizardPage;
