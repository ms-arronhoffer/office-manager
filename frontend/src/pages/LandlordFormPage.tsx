import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import { landlords as landlordsApi, attachments as attachmentsApi } from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import AddressFields, { type StructuredAddress } from '@/components/common/AddressFields';
import type { LandlordCreate } from '@/types';

interface FormValues {
  contact_name: string;
  landlord_company: string;
  contact_email: string;
  contact_phone: string;
  notes: string;
}

const emptyForm: FormValues = {
  contact_name: '',
  landlord_company: '',
  contact_email: '',
  contact_phone: '',
  notes: '',
};

const LandlordFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = Boolean(id);

  const [formValues, setFormValues] = useState<FormValues>(emptyForm);
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
          notes: l.notes ?? '',
        });
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
