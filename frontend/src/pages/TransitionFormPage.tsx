import React, { useEffect, useState } from 'react';
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
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Box from '@cloudscape-design/components/box';
import { transitions as transitionsApi, offices as officesApi, attachments as attachmentsApi } from '@/api';
import FileQueueField, { type QueuedFile } from '@/components/common/FileQueueField';
import AddressFields, {
  type StructuredAddress,
  parseUsAddress,
  formatAddress,
} from '@/components/common/AddressFields';
import type { TransitionCreate, Office } from '@/types';

type SelectOption = { label: string; value: string };

const STATUS_OPTIONS: SelectOption[] = [
  { label: 'Planned', value: 'planned' },
  { label: 'In Progress', value: 'in_progress' },
  { label: 'Completed', value: 'completed' },
  { label: 'Cancelled', value: 'cancelled' },
];

const TYPE_OPTIONS: SelectOption[] = [
  { label: 'Move', value: 'move' },
  { label: 'Closure', value: 'closure' },
  { label: 'Opening', value: 'opening' },
  { label: 'Renovation', value: 'renovation' },
];

const TransitionFormPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isEditing = !!id;

  const [loading, setLoading] = useState(isEditing);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);

  const [form, setForm] = useState<TransitionCreate>({
    office_id: undefined,
    office_number: undefined,
    transition_type: '',
    address: '',
    new_address: '',
    status: 'in_progress',
    notes: '',
  });

  const [selectedOffice, setSelectedOffice] = useState<SelectOption | null>(null);
  const [currentAddr, setCurrentAddr] = useState<StructuredAddress>({});
  const [newAddr, setNewAddr] = useState<StructuredAddress>({});
  // Original free-form text values are kept so the legacy banner has something to show
  // until the user opts to convert.
  const [legacyCurrentAddr, setLegacyCurrentAddr] = useState<string | undefined>(undefined);
  const [legacyNewAddr, setLegacyNewAddr] = useState<string | undefined>(undefined);
  const [selectedStatus, setSelectedStatus] = useState<SelectOption | null>(
    STATUS_OPTIONS.find((o) => o.value === 'in_progress') || null,
  );
  const [selectedType, setSelectedType] = useState<SelectOption | null>(null);

  // Load office options
  useEffect(() => {
    const loadOptions = async () => {
      try {
        const res = await officesApi.list({ page_size: 1000 });
        setOfficeOptions(
          res.data.items.map((o: Office) => ({ label: o.location_name, value: String(o.id) })),
        );
      } catch {
        // non-critical
      }
    };
    loadOptions();
  }, []);

  // Load existing transition when editing
  useEffect(() => {
    if (!isEditing || !id) return;
    const fetchTransition = async () => {
      try {
        const res = await transitionsApi.get(id);
        const t = res.data;
        setForm({
          office_id: t.office_id || undefined,
          office_number: t.office_number || undefined,
          transition_type: t.transition_type,
          address: t.address || '',
          new_address: t.new_address || '',
          status: t.status,
          notes: t.notes || '',
        });
        // Parse legacy free-form addresses into the structured editor.
        setCurrentAddr(parseUsAddress(t.address));
        setNewAddr(parseUsAddress(t.new_address));
        setLegacyCurrentAddr(t.address || undefined);
        setLegacyNewAddr(t.new_address || undefined);
        setSelectedType(TYPE_OPTIONS.find((o) => o.value === t.transition_type) || { label: t.transition_type, value: t.transition_type });
        setSelectedStatus(STATUS_OPTIONS.find((o) => o.value === t.status) || { label: t.status, value: t.status });
        if (t.office) {
          setSelectedOffice({ label: t.office.location_name, value: String(t.office.id) });
        }
      } catch {
        setError('Failed to load transition data.');
      } finally {
        setLoading(false);
      }
    };
    fetchTransition();
  }, [id, isEditing]);

  const handleSubmit = async () => {
    if (!selectedType) {
      setError('Transition Type is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Serialize the structured address back to a single multi-line string for storage
      // in the existing free-form `address` / `new_address` text columns. If the user
      // hasn't filled the structured fields, fall back to whatever legacy text was loaded.
      const serializedAddress =
        formatAddress(currentAddr) || legacyCurrentAddr || form.address || '';
      const serializedNewAddress =
        formatAddress(newAddr) || legacyNewAddr || form.new_address || '';

      const payload: TransitionCreate = {
        ...form,
        address: serializedAddress || undefined,
        new_address: serializedNewAddress || undefined,
        transition_type: selectedType.value,
        status: selectedStatus?.value || 'in_progress',
        office_id: selectedOffice ? selectedOffice.value : undefined,
      };
      if (isEditing && id) {
        await transitionsApi.update(id, payload);
        navigate(`/transitions/${id}`);
      } else {
        const res = await transitionsApi.create(payload);
        const newId = String(res.data.id);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('transition', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        if (failed.length > 0) {
          setError(
            `Transition created, but ${failed.length} attachment(s) failed: ${failed.join(', ')}. Re-upload from the transition page.`,
          );
        }
        navigate(`/transitions/${newId}`);
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        `Failed to ${isEditing ? 'update' : 'create'} transition.`;
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

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Transitions', href: '/transitions' },
              isEditing
                ? { text: 'Edit Transition', href: `/transitions/${id}/edit` }
                : { text: 'New Transition', href: '/transitions/new' },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header variant="h1">{isEditing ? 'Edit Transition' : 'New Transition'}</Header>
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
            <Button onClick={() => navigate(isEditing ? `/transitions/${id}` : '/transitions')}>
              Cancel
            </Button>
            <Button variant="primary" loading={saving} onClick={handleSubmit}>
              {isEditing ? 'Save Changes' : 'Create Transition'}
            </Button>
          </SpaceBetween>
        }
      >
        <Container header={<Header variant="h2">Transition Information</Header>}>
          <SpaceBetween size="l">
            <SpaceBetween direction="horizontal" size="l">
              <FormField label="Transition Type" constraintText="Required" stretch>
                <Select
                  selectedOption={selectedType}
                  onChange={({ detail }) =>
                    setSelectedType(detail.selectedOption as SelectOption)
                  }
                  options={TYPE_OPTIONS}
                  placeholder="Select type"
                />
              </FormField>
              <FormField label="Status" stretch>
                <Select
                  selectedOption={selectedStatus}
                  onChange={({ detail }) =>
                    setSelectedStatus(detail.selectedOption as SelectOption)
                  }
                  options={STATUS_OPTIONS}
                  placeholder="Select status"
                />
              </FormField>
            </SpaceBetween>

            <FormField label="Office">
              <Select
                selectedOption={selectedOffice}
                onChange={({ detail }) =>
                  setSelectedOffice(detail.selectedOption as SelectOption)
                }
                options={officeOptions}
                placeholder="Select office"
                filteringType="auto"
              />
            </FormField>

            <FormField label="Office Number">
              <Input
                type="number"
                value={form.office_number !== undefined ? String(form.office_number) : ''}
                onChange={({ detail }) =>
                  setForm((f) => ({
                    ...f,
                    office_number: detail.value ? parseInt(detail.value) : undefined,
                  }))
                }
                placeholder="e.g., 101"
              />
            </FormField>

            <FormField label="Current Address" description="Address of the existing office.">
              <AddressFields
                value={currentAddr}
                onChange={setCurrentAddr}
                disabled={saving}
                legacyAddress={legacyCurrentAddr}
              />
            </FormField>

            <FormField label="New Address" description="Address being moved to (leave empty for closures).">
              <AddressFields
                value={newAddr}
                onChange={setNewAddr}
                disabled={saving}
                legacyAddress={legacyNewAddr}
              />
            </FormField>

            <FormField label="Notes">
              <Textarea
                value={form.notes || ''}
                onChange={({ detail }) => setForm((f) => ({ ...f, notes: detail.value }))}
                placeholder="Additional notes..."
                rows={4}
              />
            </FormField>

            {!isEditing && (
              <FileQueueField files={queuedFiles} onChange={setQueuedFiles} disabled={saving} />
            )}
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
};

export default TransitionFormPage;
