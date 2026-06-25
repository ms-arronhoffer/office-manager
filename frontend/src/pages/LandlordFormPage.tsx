import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Textarea from '@cloudscape-design/components/textarea';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import { landlords as landlordsApi, offices as officesApi, attachments as attachmentsApi, managementCompanies as managementCompaniesApi } from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import {
  EntityQuickCreateSelect,
  EntityQuickCreateMultiselect,
} from '@/components/common/EntityQuickCreateSelect';
import {
  ManagementCompanyQuickCreate,
  OfficeQuickCreate,
} from '@/components/common/QuickCreateForms';
import AddressFields, { type StructuredAddress } from '@/components/common/AddressFields';
import type { LandlordCreate, Office } from '@/types';

interface SelectOption {
  label: string;
  value: string;
}

const ENTITY_TYPE_OPTIONS: SelectOption[] = [
  { label: 'Individual', value: 'Individual' },
  { label: 'Sole Proprietorship', value: 'Sole Proprietorship' },
  { label: 'LLC', value: 'LLC' },
  { label: 'Corporation', value: 'Corporation' },
  { label: 'Partnership', value: 'Partnership' },
  { label: 'Trust', value: 'Trust' },
  { label: 'Other', value: 'Other' },
];

const PAYMENT_METHOD_OPTIONS: SelectOption[] = [
  { label: 'Check', value: 'Check' },
  { label: 'ACH', value: 'ACH' },
  { label: 'Wire', value: 'Wire' },
  { label: 'Credit Card', value: 'Credit Card' },
  { label: 'Online Portal', value: 'Online Portal' },
];

interface FormValues {
  contact_name: string;
  landlord_company: string;
  contact_email: string;
  contact_phone: string;
  secondary_phone: string;
  fax: string;
  website: string;
  management_company: string;
  tax_id: string;
  payment_terms: string;
  notes: string;
}

const emptyForm: FormValues = {
  contact_name: '',
  landlord_company: '',
  contact_email: '',
  contact_phone: '',
  secondary_phone: '',
  fax: '',
  website: '',
  management_company: '',
  tax_id: '',
  payment_terms: '',
  notes: '',
};

const LandlordFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = Boolean(id);

  const [formValues, setFormValues] = useState<FormValues>(emptyForm);
  const [entityType, setEntityType] = useState<SelectOption | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<SelectOption | null>(null);
  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);
  const [selectedOffices, setSelectedOffices] = useState<SelectOption[]>([]);
  const [mgmtCompanyOptions, setMgmtCompanyOptions] = useState<SelectOption[]>([]);
  const [selectedMgmtCompany, setSelectedMgmtCompany] = useState<SelectOption | null>(null);
  const [propertyAddress, setPropertyAddress] = useState<StructuredAddress>({});
  const [mailingAddress, setMailingAddress] = useState<StructuredAddress>({});
  // Legacy free-form values from existing records, kept so we don't wipe them on save.
  const [legacyAddress, setLegacyAddress] = useState<string | undefined>(undefined);
  const [legacyMailing, setLegacyMailing] = useState<string | undefined>(undefined);
  const [loadingData, setLoadingData] = useState(isEdit);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);

  useEffect(() => {
    const loadOffices = async () => {
      try {
        const res = await officesApi.list({ page_size: 1000 });
        setOfficeOptions(
          res.data.items.map((o: Office) => ({ label: o.location_name, value: String(o.id) })),
        );
      } catch {
        // non-critical
      }
    };
    loadOffices();
  }, []);

  useEffect(() => {
    const loadMgmtCompanies = async () => {
      try {
        const res = await managementCompaniesApi.list({ page_size: 1000 });
        setMgmtCompanyOptions(
          res.data.items.map((c) => ({ label: c.name, value: String(c.id) })),
        );
      } catch {
        // non-critical
      }
    };
    loadMgmtCompanies();
  }, []);

  useEffect(() => {
    if (!isEdit || !id) return;
    const fetchLandlord = async () => {
      try {
        const res = await landlordsApi.get(id);
        const l = res.data;
        setFormValues({
          contact_name: l.contact_name ?? '',
          landlord_company: l.landlord_company ?? '',
          contact_email: l.contact_email ?? '',
          contact_phone: l.contact_phone ?? '',
          secondary_phone: l.secondary_phone ?? '',
          fax: l.fax ?? '',
          website: l.website ?? '',
          management_company: l.management_company ?? '',
          tax_id: l.tax_id ?? '',
          payment_terms: l.payment_terms ?? '',
          notes: l.notes ?? '',
        });
        setEntityType(l.entity_type ? { label: l.entity_type, value: l.entity_type } : null);
        setPaymentMethod(
          l.preferred_payment_method
            ? { label: l.preferred_payment_method, value: l.preferred_payment_method }
            : null,
        );
        setSelectedOffices(
          (l.owned_offices ?? []).map((o) => ({ label: o.location_name, value: String(o.id) })),
        );
        if (l.management_company_ref) {
          setSelectedMgmtCompany({
            label: l.management_company_ref.name,
            value: String(l.management_company_ref.id),
          });
        }
        setPropertyAddress({
          address_line_1: l.address_line_1,
          address_line_2: l.address_line_2,
          city: l.city,
          state: l.state,
          zip_code: l.zip_code,
        });
        setMailingAddress({
          address_line_1: l.mailing_address_line_1,
          address_line_2: l.mailing_address_line_2,
          city: l.mailing_city,
          state: l.mailing_state,
          zip_code: l.mailing_zip_code,
        });
        setLegacyAddress(l.address || undefined);
        setLegacyMailing(l.contact_mailing_address || undefined);
      } catch {
        setLoadError('Failed to load landlord data.');
      } finally {
        setLoadingData(false);
      }
    };
    fetchLandlord();
  }, [id, isEdit]);

  const setField = <K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setFormValues((prev) => ({ ...prev, [key]: value }));
    if (key === 'contact_name') setNameError(undefined);
  };

  const validate = (): boolean => {
    if (!formValues.contact_name.trim()) {
      setNameError('Name is required.');
      return false;
    }
    return true;
  };

  const handleSubmit = async () => {
    if (!validate()) return;

    setSubmitting(true);
    setSubmitError(null);

    const payload: LandlordCreate = {
      contact_name: formValues.contact_name.trim(),
      landlord_company: formValues.landlord_company.trim() || undefined,
      contact_email: formValues.contact_email.trim() || undefined,
      contact_phone: formValues.contact_phone.trim() || undefined,
      secondary_phone: formValues.secondary_phone.trim() || undefined,
      fax: formValues.fax.trim() || undefined,
      website: formValues.website.trim() || undefined,
      management_company: formValues.management_company.trim() || undefined,
      management_company_id: selectedMgmtCompany?.value || null,
      entity_type: entityType?.value || undefined,
      tax_id: formValues.tax_id.trim() || undefined,
      preferred_payment_method: paymentMethod?.value || undefined,
      payment_terms: formValues.payment_terms.trim() || undefined,
      // Offices owned by this landlord (one or many).
      office_ids: selectedOffices.map((o) => o.value),
      // Structured property address.
      address_line_1: propertyAddress.address_line_1?.trim() || undefined,
      address_line_2: propertyAddress.address_line_2?.trim() || undefined,
      city: propertyAddress.city?.trim() || undefined,
      state: propertyAddress.state?.trim() || undefined,
      zip_code: propertyAddress.zip_code?.trim() || undefined,
      // Structured mailing address.
      mailing_address_line_1: mailingAddress.address_line_1?.trim() || undefined,
      mailing_address_line_2: mailingAddress.address_line_2?.trim() || undefined,
      mailing_city: mailingAddress.city?.trim() || undefined,
      mailing_state: mailingAddress.state?.trim() || undefined,
      mailing_zip_code: mailingAddress.zip_code?.trim() || undefined,
      // Preserve any legacy free-form values so old data isn't lost on edit.
      address: legacyAddress?.trim() || undefined,
      contact_mailing_address: legacyMailing?.trim() || undefined,
      notes: formValues.notes.trim() || undefined,
    };

    try {
      if (isEdit && id) {
        await landlordsApi.update(id, payload);
        navigate(`/landlords/${id}`);
      } else {
        const res = await landlordsApi.create(payload);
        const newId = String(res.data.id);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('landlord', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        if (failed.length > 0) {
          setSubmitError(
            `Landlord created, but ${failed.length} attachment(s) failed: ${failed.join(', ')}. Re-upload from the landlord page.`,
          );
        }
        navigate(`/landlords/${newId}`);
      }
    } catch {
      setSubmitError(
        isEdit ? 'Failed to update landlord. Please try again.' : 'Failed to create landlord. Please try again.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingData) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (loadError) {
    return <Alert type="error">{loadError}</Alert>;
  }

  const pageTitle = isEdit ? 'Edit Landlord' : 'Create Landlord';

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Home', href: '/' },
              { text: 'Landlords', href: '/landlords' },
              { text: pageTitle, href: isEdit ? `/landlords/${id}/edit` : '/landlords/new' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header variant="h1">{pageTitle}</Header>
        </SpaceBetween>
      }
    >
      <form onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => navigate(-1)}>
                Cancel
              </Button>
              <Button variant="primary" loading={submitting} onClick={handleSubmit}>
                {isEdit ? 'Save changes' : 'Create landlord'}
              </Button>
            </SpaceBetween>
          }
          errorText={submitError ?? undefined}
        >
          <Container header={<Header variant="h2">Landlord details</Header>}>
            <SpaceBetween size="l">
              <FormField label="Contact Name" errorText={nameError} constraintText="Required">
                <Input
                  value={formValues.contact_name}
                  onChange={({ detail }) => setField('contact_name', detail.value)}
                  placeholder="Enter contact name"
                />
              </FormField>

              <FormField label="Landlord Company">
                <Input
                  value={formValues.landlord_company}
                  onChange={({ detail }) => setField('landlord_company', detail.value)}
                  placeholder="Enter company name"
                />
              </FormField>

              <FormField label="Email">
                <Input
                  value={formValues.contact_email}
                  onChange={({ detail }) => setField('contact_email', detail.value)}
                  type="email"
                  placeholder="Enter email address"
                />
              </FormField>

              <FormField label="Phone">
                <Input
                  value={formValues.contact_phone}
                  onChange={({ detail }) => setField('contact_phone', detail.value)}
                  type="tel"
                  placeholder="Enter phone number"
                />
              </FormField>

              <FormField label="Secondary Phone">
                <Input
                  value={formValues.secondary_phone}
                  onChange={({ detail }) => setField('secondary_phone', detail.value)}
                  placeholder="Enter a secondary phone number"
                />
              </FormField>

              <FormField label="Fax">
                <Input
                  value={formValues.fax}
                  onChange={({ detail }) => setField('fax', detail.value)}
                  placeholder="Enter fax number"
                />
              </FormField>

              <FormField label="Website">
                <Input
                  value={formValues.website}
                  onChange={({ detail }) => setField('website', detail.value)}
                  type="url"
                  placeholder="https://example.com"
                />
              </FormField>

              <Header variant="h3">Business Details</Header>

              <FormField label="Entity Type">
                <Select
                  selectedOption={entityType}
                  onChange={({ detail }) => setEntityType(detail.selectedOption as SelectOption)}
                  options={ENTITY_TYPE_OPTIONS}
                  placeholder="Select entity type"
                />
              </FormField>

              <FormField
                label="Property Management Company"
                description="Link this landlord to a management company record. Manage these under Portfolio → Property Management."
              >
                <EntityQuickCreateSelect
                  selectedOption={selectedMgmtCompany}
                  onChange={(opt) =>
                    setSelectedMgmtCompany(opt && opt.value ? opt : null)
                  }
                  options={[{ label: 'None', value: '' }, ...mgmtCompanyOptions]}
                  placeholder="Select a management company"
                  empty="No management companies found"
                  quickCreate={{
                    label: '+ Add new management company…',
                    render: ({ visible, onClose, onCreated }) => (
                      <ManagementCompanyQuickCreate
                        visible={visible}
                        onClose={onClose}
                        onCreated={onCreated}
                      />
                    ),
                  }}
                />
              </FormField>

              <FormField label="Tax ID / EIN">
                <Input
                  value={formValues.tax_id}
                  onChange={({ detail }) => setField('tax_id', detail.value)}
                  placeholder="Enter Tax ID or EIN"
                />
              </FormField>

              <FormField
                label="Owned Offices"
                description="Offices owned by this landlord (one or many)."
              >
                <EntityQuickCreateMultiselect
                  selectedOptions={selectedOffices}
                  onChange={(opts) => setSelectedOffices(opts)}
                  options={officeOptions}
                  placeholder="Select offices"
                  tokenLimit={5}
                  quickCreate={{
                    label: '+ Add new office…',
                    render: ({ visible, onClose, onCreated }) => (
                      <OfficeQuickCreate
                        visible={visible}
                        onClose={onClose}
                        onCreated={onCreated}
                      />
                    ),
                  }}
                />
              </FormField>

              <Header variant="h3">Billing</Header>

              <FormField label="Preferred Payment Method">
                <Select
                  selectedOption={paymentMethod}
                  onChange={({ detail }) => setPaymentMethod(detail.selectedOption as SelectOption)}
                  options={PAYMENT_METHOD_OPTIONS}
                  placeholder="Select payment method"
                />
              </FormField>

              <FormField label="Payment Terms">
                <Input
                  value={formValues.payment_terms}
                  onChange={({ detail }) => setField('payment_terms', detail.value)}
                  placeholder="e.g., Net 30"
                />
              </FormField>

              <Header variant="h3">Property Address</Header>
              <AddressFields
                value={propertyAddress}
                onChange={setPropertyAddress}
                disabled={submitting}
                legacyAddress={legacyAddress}
              />

              <Header variant="h3">Mailing Address</Header>
              <AddressFields
                value={mailingAddress}
                onChange={setMailingAddress}
                disabled={submitting}
                legacyAddress={legacyMailing}
              />

              <FormField label="Notes">
                <Textarea
                  value={formValues.notes}
                  onChange={({ detail }) => setField('notes', detail.value)}
                  placeholder="Enter any notes"
                  rows={4}
                />
              </FormField>

              {!isEdit && (
                <FileQueueField files={queuedFiles} onChange={setQueuedFiles} disabled={submitting} />
              )}
            </SpaceBetween>
          </Container>
        </Form>
      </form>
    </ContentLayout>
  );
};

export default LandlordFormPage;
