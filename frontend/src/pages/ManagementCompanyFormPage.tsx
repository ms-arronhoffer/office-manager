import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import type { InputProps } from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import { managementCompanies as api } from '@/api';
import AddressFields, { type StructuredAddress } from '@/components/common/AddressFields';
import type { ManagementCompanyCreate } from '@/types';

const emptyForm = {
  name: '',
  contact_name: '',
  contact_title: '',
  contact_email: '',
  contact_phone: '',
  secondary_phone: '',
  fax: '',
  website: '',
  portal_url: '',
  notes: '',
};

const ManagementCompanyFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = Boolean(id);

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [form, setForm] = useState({ ...emptyForm });
  const [address, setAddress] = useState<StructuredAddress>({});
  const nameRef = React.useRef<InputProps.Ref>(null);

  useEffect(() => {
    if (!isEdit || !id) return;
    const fetchCompany = async () => {
      try {
        const res = await api.get(id);
        const c = res.data;
        setForm({
          name: c.name || '',
          contact_name: c.contact_name || '',
          contact_title: c.contact_title || '',
          contact_email: c.contact_email || '',
          contact_phone: c.contact_phone || '',
          secondary_phone: c.secondary_phone || '',
          fax: c.fax || '',
          website: c.website || '',
          portal_url: c.portal_url || '',
          notes: c.notes || '',
        });
        setAddress({
          address_line_1: c.address_line_1,
          address_line_2: c.address_line_2,
          city: c.city,
          state: c.state,
          zip_code: c.zip_code,
        });
      } catch {
        setError('Failed to load management company data.');
      } finally {
        setLoading(false);
      }
    };
    fetchCompany();
  }, [id, isEdit]);

  const setField = (key: keyof typeof emptyForm, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    if (key === 'name') setNameError(undefined);
  };

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      setNameError('Company Name is required.');
      setError('Company Name is required.');
      nameRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    const payload: ManagementCompanyCreate = {
      name: form.name.trim(),
      contact_name: form.contact_name.trim() || undefined,
      contact_title: form.contact_title.trim() || undefined,
      contact_email: form.contact_email.trim() || undefined,
      contact_phone: form.contact_phone.trim() || undefined,
      secondary_phone: form.secondary_phone.trim() || undefined,
      fax: form.fax.trim() || undefined,
      website: form.website.trim() || undefined,
      portal_url: form.portal_url.trim() || undefined,
      address_line_1: address.address_line_1?.trim() || undefined,
      address_line_2: address.address_line_2?.trim() || undefined,
      city: address.city?.trim() || undefined,
      state: address.state?.trim() || undefined,
      zip_code: address.zip_code?.trim() || undefined,
      notes: form.notes.trim() || undefined,
    };
    try {
      if (isEdit && id) {
        await api.update(id, payload);
        navigate(`/management-companies/${id}`);
      } else {
        const res = await api.create(payload);
        navigate(`/management-companies/${res.data.id}`);
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        `Failed to ${isEdit ? 'update' : 'create'} management company.`;
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  const pageTitle = isEdit ? 'Edit Management Company' : 'New Management Company';

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Property Management', href: '/management-companies' },
              isEdit
                ? { text: 'Edit Management Company', href: `/management-companies/${id}/edit` }
                : { text: 'New Management Company', href: '/management-companies/new' },
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
      {error && (
        <Alert type="error" dismissible onDismiss={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate(isEdit ? `/management-companies/${id}` : '/management-companies')}>
              Cancel
            </Button>
            <Button variant="primary" loading={saving} onClick={handleSubmit}>
              {isEdit ? 'Save Changes' : 'Create Management Company'}
            </Button>
          </SpaceBetween>
        }
      >
        <Container header={<Header variant="h2">Company Information</Header>}>
          <SpaceBetween size="l">
            <FormField label="Company Name" errorText={nameError} constraintText="Required">
              <Input
                ref={nameRef}
                value={form.name}
                onChange={({ detail }) => setField('name', detail.value)}
                placeholder="Enter company name"
                invalid={!!nameError}
              />
            </FormField>

            <Header variant="h3">Primary Contact</Header>
            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Contact Name" stretch>
                <Input
                  value={form.contact_name}
                  onChange={({ detail }) => setField('contact_name', detail.value)}
                  placeholder="Contact person"
                />
              </FormField>
              <FormField label="Title" stretch>
                <Input
                  value={form.contact_title}
                  onChange={({ detail }) => setField('contact_title', detail.value)}
                  placeholder="e.g., Regional Director"
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Email" stretch>
                <Input
                  value={form.contact_email}
                  onChange={({ detail }) => setField('contact_email', detail.value)}
                  placeholder="Email address"
                  type="email"
                />
              </FormField>
              <FormField label="Phone" stretch>
                <Input
                  value={form.contact_phone}
                  onChange={({ detail }) => setField('contact_phone', detail.value)}
                  placeholder="Phone number"
                />
              </FormField>
            </SpaceBetween>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Secondary Phone" stretch>
                <Input
                  value={form.secondary_phone}
                  onChange={({ detail }) => setField('secondary_phone', detail.value)}
                  placeholder="Secondary phone"
                />
              </FormField>
              <FormField label="Fax" stretch>
                <Input
                  value={form.fax}
                  onChange={({ detail }) => setField('fax', detail.value)}
                  placeholder="Fax number"
                />
              </FormField>
            </SpaceBetween>

            <Header variant="h3">Web</Header>
            <FormField label="Website">
              <Input
                value={form.website}
                onChange={({ detail }) => setField('website', detail.value)}
                type="url"
                placeholder="https://example.com"
              />
            </FormField>
            <FormField label="Online Portal URL">
              <Input
                value={form.portal_url}
                onChange={({ detail }) => setField('portal_url', detail.value)}
                type="url"
                placeholder="https://portal.example.com"
              />
            </FormField>

            <Header variant="h3">Address</Header>
            <AddressFields value={address} onChange={setAddress} disabled={saving} />

            <FormField label="Notes">
              <Textarea
                value={form.notes}
                onChange={({ detail }) => setField('notes', detail.value)}
                placeholder="Additional notes..."
                rows={4}
              />
            </FormField>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
};

export default ManagementCompanyFormPage;
