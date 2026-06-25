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
import Select from '@cloudscape-design/components/select';
import DatePicker from '@cloudscape-design/components/date-picker';
import Toggle from '@cloudscape-design/components/toggle';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import {
  hvacContracts as hvacContractsApi,
  offices as officesApi,
  managers as managersApi,
  attachments as attachmentsApi,
} from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import { useUnsavedChangesWarning } from '@/hooks/useUnsavedChangesWarning';
import type { HvacContractCreate, Office, Manager } from '@/types';

type SelectOption = { label: string; value: string };

const FREQUENCY_OPTIONS: SelectOption[] = [
  { label: 'Monthly', value: 'Monthly' },
  { label: 'Quarterly', value: 'Quarterly' },
  { label: 'Bi-Annual', value: 'Bi-Annual' },
  { label: 'Annual', value: 'Annual' },
  { label: 'On-Demand', value: 'On-Demand' },
];

interface FormValues {
  hvac_company: string;
  contact: string;
  comments: string;
  office_name: string;
  office_number: string;
  last_serviced: string;
  next_service: string;
  last_serviced_date: string;
  next_service_date: string;
  landlord_handles: boolean;
}

const emptyForm: FormValues = {
  hvac_company: '',
  contact: '',
  comments: '',
  office_name: '',
  office_number: '',
  last_serviced: '',
  next_service: '',
  last_serviced_date: '',
  next_service_date: '',
  landlord_handles: false,
};

const HvacContractFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEdit = Boolean(id);

  const [form, setForm] = useState<FormValues>(emptyForm);
  const [selectedOffice, setSelectedOffice] = useState<SelectOption | null>(null);
  const [selectedManager, setSelectedManager] = useState<SelectOption | null>(null);
  const [selectedFrequency, setSelectedFrequency] = useState<SelectOption | null>(null);
  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);
  const [managerOptions, setManagerOptions] = useState<SelectOption[]>([]);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [companyError, setCompanyError] = useState<string | undefined>(undefined);
  const [dirty, setDirty] = useState(false);

  useUnsavedChangesWarning(dirty && !saving);

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const [offRes, mgrRes] = await Promise.all([
          officesApi.list({ page_size: 1000 }),
          managersApi.list(),
        ]);
        setOfficeOptions(
          offRes.data.items.map((o: Office) => ({ label: o.location_name, value: String(o.id) })),
        );
        setManagerOptions(
          mgrRes.data.map((m: Manager) => ({ label: m.name, value: String(m.id) })),
        );
      } catch {
        // Non-critical: dropdowns will just be empty
      }
    };
    loadOptions();
  }, []);

  useEffect(() => {
    if (!isEdit || !id) return;
    const fetchContract = async () => {
      try {
        const res = await hvacContractsApi.get(id);
        const c = res.data;
        setForm({
          hvac_company: c.hvac_company ?? '',
          contact: c.contact ?? '',
          comments: c.comments ?? '',
          office_name: c.office_name ?? '',
          office_number: c.office_number != null ? String(c.office_number) : '',
          last_serviced: c.last_serviced ?? '',
          next_service: c.next_service ?? '',
          last_serviced_date: c.last_serviced_date ?? '',
          next_service_date: c.next_service_date ?? '',
          landlord_handles: c.landlord_handles ?? false,
        });
        if (c.office_id) {
          // office relationship may not be hydrated; show id-only label as fallback
          setSelectedOffice({
            label: c.office_name || c.office_id,
            value: String(c.office_id),
          });
        }
        if (c.manager) {
          setSelectedManager({ label: c.manager.name, value: String(c.manager.id) });
        }
        if (c.frequency) {
          setSelectedFrequency({ label: c.frequency, value: c.frequency });
        }
      } catch {
        setError('Failed to load HVAC contract data.');
      } finally {
        setLoading(false);
      }
    };
    fetchContract();
  }, [id, isEdit]);

  const setField = <K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
    if (key === 'hvac_company') setCompanyError(undefined);
  };

  const validate = (): boolean => {
    if (!form.hvac_company.trim()) {
      setCompanyError('HVAC Company is required.');
      return false;
    }
    return true;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    setSaving(true);
    setError(null);
    try {
      const payload: HvacContractCreate = {
        hvac_company: form.hvac_company.trim() || undefined,
        contact: form.contact.trim() || undefined,
        comments: form.comments.trim() || undefined,
        office_name: form.office_name.trim() || undefined,
        office_number: form.office_number ? parseInt(form.office_number, 10) : undefined,
        office_id: selectedOffice ? selectedOffice.value : undefined,
        manager_id: selectedManager ? selectedManager.value : undefined,
        frequency: selectedFrequency ? selectedFrequency.value : undefined,
        last_serviced: form.last_serviced.trim() || undefined,
        next_service: form.next_service.trim() || undefined,
        last_serviced_date: form.last_serviced_date || undefined,
        next_service_date: form.next_service_date || undefined,
        landlord_handles: form.landlord_handles,
      };

      if (isEdit && id) {
        await hvacContractsApi.update(id, payload);
        setDirty(false);
        navigate(`/hvac-contracts/${id}`);
      } else {
        const res = await hvacContractsApi.create(payload);
        const newId = String(res.data.id);
        setDirty(false);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('hvac_contract', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        if (failed.length > 0) {
          setError(
            `Contract created, but ${failed.length} attachment(s) failed to upload: ${failed.join(', ')}. ` +
              'You can retry from the contract page.',
          );
        }
        navigate(`/hvac-contracts/${newId}`);
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        `Failed to ${isEdit ? 'update' : 'create'} HVAC contract.`;
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

  const pageTitle = isEdit ? 'Edit HVAC Contract' : 'Create HVAC Contract';

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Home', href: '/' },
              { text: 'HVAC Contracts', href: '/hvac-contracts' },
              {
                text: pageTitle,
                href: isEdit ? `/hvac-contracts/${id}/edit` : '/hvac-contracts/new',
              },
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
      <form onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <Form
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => navigate(-1)}>
                Cancel
              </Button>
              <Button variant="primary" loading={saving} onClick={handleSubmit}>
                {isEdit ? 'Save changes' : 'Create contract'}
              </Button>
            </SpaceBetween>
          }
        >
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Contract details</Header>}>
              <SpaceBetween size="l">
                <FormField
                  label="HVAC Company"
                  errorText={companyError}
                  constraintText="Required"
                >
                  <Input
                    value={form.hvac_company}
                    onChange={({ detail }) => setField('hvac_company', detail.value)}
                    placeholder="Enter HVAC company name"
                  />
                </FormField>

                <FormField label="Contact">
                  <Input
                    value={form.contact}
                    onChange={({ detail }) => setField('contact', detail.value)}
                    placeholder="Primary contact (name / phone / email)"
                  />
                </FormField>

                <FormField label="Office">
                  <Select
                    selectedOption={selectedOffice}
                    onChange={({ detail }) =>
                      setSelectedOffice(detail.selectedOption as SelectOption | null)
                    }
                    options={officeOptions}
                    placeholder="Select an office"
                    filteringType="auto"
                    empty="No offices available"
                  />
                </FormField>

                <SpaceBetween direction="horizontal" size="l">
                  <FormField label="Office Name (override)" stretch>
                    <Input
                      value={form.office_name}
                      onChange={({ detail }) => setField('office_name', detail.value)}
                      placeholder="Optional"
                    />
                  </FormField>
                  <FormField label="Office Number" stretch>
                    <Input
                      value={form.office_number}
                      type="number"
                      inputMode="numeric"
                      onChange={({ detail }) => setField('office_number', detail.value)}
                      placeholder="e.g. 101"
                    />
                  </FormField>
                </SpaceBetween>

                <FormField label="Manager">
                  <Select
                    selectedOption={selectedManager}
                    onChange={({ detail }) =>
                      setSelectedManager(detail.selectedOption as SelectOption | null)
                    }
                    options={managerOptions}
                    placeholder="Select a manager"
                    filteringType="auto"
                    empty="No managers available"
                  />
                </FormField>

                <FormField label="Service Frequency">
                  <Select
                    selectedOption={selectedFrequency}
                    onChange={({ detail }) =>
                      setSelectedFrequency(detail.selectedOption as SelectOption | null)
                    }
                    options={FREQUENCY_OPTIONS}
                    placeholder="Select frequency"
                  />
                </FormField>

                <SpaceBetween direction="horizontal" size="l">
                  <FormField label="Last Serviced (date)" stretch>
                    <DatePicker
                      value={form.last_serviced_date}
                      onChange={({ detail }) => setField('last_serviced_date', detail.value)}
                      placeholder="YYYY/MM/DD"
                    />
                  </FormField>
                  <FormField label="Next Service (date)" stretch>
                    <DatePicker
                      value={form.next_service_date}
                      onChange={({ detail }) => setField('next_service_date', detail.value)}
                      placeholder="YYYY/MM/DD"
                    />
                  </FormField>
                </SpaceBetween>

                <SpaceBetween direction="horizontal" size="l">
                  <FormField
                    label="Last Serviced (text)"
                    description="Free-form value when an exact date isn't known."
                    stretch
                  >
                    <Input
                      value={form.last_serviced}
                      onChange={({ detail }) => setField('last_serviced', detail.value)}
                      placeholder='e.g. "Spring 2025"'
                    />
                  </FormField>
                  <FormField label="Next Service (text)" stretch>
                    <Input
                      value={form.next_service}
                      onChange={({ detail }) => setField('next_service', detail.value)}
                      placeholder='e.g. "Fall 2026"'
                    />
                  </FormField>
                </SpaceBetween>

                <FormField label="Landlord handles HVAC">
                  <Toggle
                    checked={form.landlord_handles}
                    onChange={({ detail }) => setField('landlord_handles', detail.checked)}
                  >
                    {form.landlord_handles ? 'Yes' : 'No'}
                  </Toggle>
                </FormField>

                <FormField label="Comments">
                  <Textarea
                    value={form.comments}
                    onChange={({ detail }) => setField('comments', detail.value)}
                    placeholder="Additional notes..."
                    rows={4}
                  />
                </FormField>

                {!isEdit && (
                  <FileQueueField
                    files={queuedFiles}
                    onChange={setQueuedFiles}
                    disabled={saving}
                  />
                )}
              </SpaceBetween>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
};

export default HvacContractFormPage;
