import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Checkbox from '@cloudscape-design/components/checkbox';
import Toggle from '@cloudscape-design/components/toggle';
import Multiselect from '@cloudscape-design/components/multiselect';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import Icon from '@cloudscape-design/components/icon';
import { vendors as vendorsApi, offices as officesApi, attachments as attachmentsApi, ticketCategories as categoriesApi } from '@/api';
import AddressFields, { type StructuredAddress } from '@/components/common/AddressFields';
import type { VendorCreate, Office, TicketCategory } from '@/types';

type PendingAttachment = { file: File; description: string };

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type SelectOption = { label: string; value: string };

const VendorFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = Boolean(id);

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);
  const [selectedOffices, setSelectedOffices] = useState<SelectOption[]>([]);
  const [categories, setCategories] = useState<TicketCategory[]>([]);
  const [selectedServices, setSelectedServices] = useState<string[]>([]);

  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const [form, setForm] = useState({
    company_name: '',
    contact_name: '',
    contact_email: '',
    contact_phone: '',
    is_preferred: false,
    notes: '',
  });
  const [address, setAddress] = useState<StructuredAddress>({});
  // Legacy free-form address from existing records, kept for the "Use this" banner.
  const [legacyAddress, setLegacyAddress] = useState<string | undefined>(undefined);

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const [offRes, catRes] = await Promise.all([
          officesApi.list({ page_size: 1000 }),
          categoriesApi.list(),
        ]);
        setOfficeOptions(
          offRes.data.items.map((o: Office) => ({ label: o.location_name, value: String(o.id) })),
        );
        setCategories(Array.isArray(catRes.data) ? catRes.data : []);
      } catch {
        // non-critical
      }
    };
    loadOptions();
  }, []);

  useEffect(() => {
    if (!isEdit || !id) return;
    const fetchVendor = async () => {
      try {
        const res = await vendorsApi.get(id);
        const v = res.data;
        setForm({
          company_name: v.company_name || '',
          contact_name: v.contact_name || '',
          contact_email: v.contact_email || '',
          contact_phone: v.contact_phone || '',
          is_preferred: v.is_preferred ?? false,
          notes: v.notes || '',
        });
        // Parse comma-separated services string back to selected category names.
        const parsed = (v.services || '')
          .split(',')
          .map((s: string) => s.trim())
          .filter(Boolean);
        setSelectedServices(parsed);
        setAddress({
          address_line_1: v.address_line_1,
          address_line_2: v.address_line_2,
          city: v.city,
          state: v.state,
          zip_code: v.zip_code,
        });
        setLegacyAddress(v.address || undefined);
        if (v.offices?.length) {
          setSelectedOffices(
            v.offices.map((o) => ({ label: o.location_name, value: String(o.id) })),
          );
        }
      } catch {
        setError('Failed to load vendor data.');
      } finally {
        setLoading(false);
      }
    };
    fetchVendor();
  }, [id, isEdit]);

  const handleSubmit = async () => {
    if (!form.company_name.trim()) {
      setError('Company Name is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: VendorCreate = {
        company_name: form.company_name.trim(),
        services: selectedServices.length > 0 ? selectedServices.join(', ') : undefined,
        contact_name: form.contact_name.trim() || undefined,
        contact_email: form.contact_email.trim() || undefined,
        contact_phone: form.contact_phone.trim() || undefined,
        // Structured address fields (preferred).
        address_line_1: address.address_line_1?.trim() || undefined,
        address_line_2: address.address_line_2?.trim() || undefined,
        city: address.city?.trim() || undefined,
        state: address.state?.trim() || undefined,
        zip_code: address.zip_code?.trim() || undefined,
        // Preserve the legacy free-form address on edit so prior data isn't wiped.
        address: legacyAddress?.trim() || undefined,
        is_preferred: form.is_preferred,
        notes: form.notes.trim() || undefined,
        office_ids: selectedOffices.map((o) => o.value),
      };
      if (isEdit && id) {
        await vendorsApi.update(id, payload);
        navigate(`/vendors/${id}`);
      } else {
        const res = await vendorsApi.create(payload);
        const newVendorId = res.data.id;

        if (pendingAttachments.length > 0) {
          const failed: string[] = [];
          for (const item of pendingAttachments) {
            try {
              await attachmentsApi.upload(
                'vendor',
                String(newVendorId),
                item.file,
                item.description || undefined,
              );
            } catch {
              failed.push(item.file.name);
            }
          }
          if (failed.length > 0) {
            setWarning(
              `Vendor created, but ${failed.length} attachment(s) failed to upload: ${failed.join(', ')}. You can re-upload them from the vendor page.`,
            );
          }
        }

        navigate(`/vendors/${newVendorId}`);
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        `Failed to ${isEdit ? 'update' : 'create'} vendor.`;
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

  const pageTitle = isEdit ? 'Edit Vendor' : 'New Vendor';

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Vendors', href: '/vendors' },
              isEdit
                ? { text: 'Edit Vendor', href: `/vendors/${id}/edit` }
                : { text: 'New Vendor', href: '/vendors/new' },
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
      {warning && (
        <Alert type="warning" dismissible onDismiss={() => setWarning(null)}>
          {warning}
        </Alert>
      )}
      <Form
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate(isEdit ? `/vendors/${id}` : '/vendors')}>
              Cancel
            </Button>
            <Button variant="primary" loading={saving} onClick={handleSubmit}>
              {isEdit ? 'Save Changes' : 'Create Vendor'}
            </Button>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="l">
        <Container header={<Header variant="h2">Vendor Information</Header>}>
          <SpaceBetween size="l">
            <FormField label="Company Name" constraintText="Required">
              <Input
                value={form.company_name}
                onChange={({ detail }) => setForm((f) => ({ ...f, company_name: detail.value }))}
                placeholder="Enter company name"
              />
            </FormField>

            <FormField
              label="Services"
              description="Select all categories this vendor provides. Manage categories in Settings → Ticket Categories."
            >
              <SpaceBetween size="xs">
                {categories.map((cat) => (
                  <Checkbox
                    key={cat.id}
                    checked={selectedServices.includes(cat.name)}
                    onChange={({ detail }) =>
                      setSelectedServices((prev) =>
                        detail.checked
                          ? [...prev, cat.name]
                          : prev.filter((s) => s !== cat.name),
                      )
                    }
                  >
                    {cat.name}
                  </Checkbox>
                ))}
                {categories.length === 0 && (
                  <Box color="text-status-inactive">
                    No categories defined. Add them in Settings → Ticket Categories.
                  </Box>
                )}
              </SpaceBetween>
            </FormField>

            <FormField label="Preferred Vendor">
              <Toggle
                checked={form.is_preferred}
                onChange={({ detail }) => setForm((f) => ({ ...f, is_preferred: detail.checked }))}
              >
                {form.is_preferred ? 'Yes' : 'No'}
              </Toggle>
            </FormField>

            <FormField label="Assigned Offices">
              <Multiselect
                selectedOptions={selectedOffices}
                onChange={({ detail }) =>
                  setSelectedOffices(detail.selectedOptions as SelectOption[])
                }
                options={officeOptions}
                placeholder="Select offices"
                filteringType="auto"
                tokenLimit={5}
              />
            </FormField>

            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Contact Name" stretch>
                <Input
                  value={form.contact_name}
                  onChange={({ detail }) => setForm((f) => ({ ...f, contact_name: detail.value }))}
                  placeholder="Contact person"
                />
              </FormField>
              <FormField label="Email" stretch>
                <Input
                  value={form.contact_email}
                  onChange={({ detail }) => setForm((f) => ({ ...f, contact_email: detail.value }))}
                  placeholder="Email address"
                  type="email"
                />
              </FormField>
              <FormField label="Phone" stretch>
                <Input
                  value={form.contact_phone}
                  onChange={({ detail }) => setForm((f) => ({ ...f, contact_phone: detail.value }))}
                  placeholder="Phone number"
                />
              </FormField>
            </SpaceBetween>

            <AddressFields
              value={address}
              onChange={setAddress}
              disabled={saving}
              legacyAddress={legacyAddress}
            />

            <FormField label="Notes">
              <Textarea
                value={form.notes}
                onChange={({ detail }) => setForm((f) => ({ ...f, notes: detail.value }))}
                placeholder="Additional notes..."
                rows={4}
              />
            </FormField>
          </SpaceBetween>
        </Container>

        {!isEdit && (
          <Container
            header={
              <Header
                variant="h2"
                description="Files selected here will be uploaded after the vendor is created."
              >
                Attachments
              </Header>
            }
          >
            <SpaceBetween size="m">
              <FormField label="Add files">
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={(e) => {
                    const files = e.target.files ? Array.from(e.target.files) : [];
                    if (files.length > 0) {
                      setPendingAttachments((prev) => [
                        ...prev,
                        ...files.map((f) => ({ file: f, description: '' })),
                      ]);
                    }
                    if (fileInputRef.current) fileInputRef.current.value = '';
                  }}
                />
              </FormField>

              {pendingAttachments.length > 0 && (
                <SpaceBetween size="s">
                  {pendingAttachments.map((item, idx) => (
                    <Box key={`${item.file.name}-${idx}`} padding="s">
                      <SpaceBetween size="xs">
                        <SpaceBetween direction="horizontal" size="s">
                          <Icon name="file" />
                          <Box variant="strong">{item.file.name}</Box>
                          <Box color="text-status-inactive">
                            ({formatFileSize(item.file.size)})
                          </Box>
                          <Button
                            variant="inline-link"
                            onClick={() =>
                              setPendingAttachments((prev) =>
                                prev.filter((_, i) => i !== idx),
                              )
                            }
                          >
                            Remove
                          </Button>
                        </SpaceBetween>
                        <Input
                          value={item.description}
                          onChange={({ detail }) =>
                            setPendingAttachments((prev) =>
                              prev.map((p, i) =>
                                i === idx ? { ...p, description: detail.value } : p,
                              ),
                            )
                          }
                          placeholder="Optional description"
                        />
                      </SpaceBetween>
                    </Box>
                  ))}
                </SpaceBetween>
              )}
            </SpaceBetween>
          </Container>
        )}
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
};

export default VendorFormPage;
