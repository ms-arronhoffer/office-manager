import React, { useCallback, useEffect, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Checkbox from '@cloudscape-design/components/checkbox';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import { useFlashbar } from '@/context/FlashbarContext';
import { applicationTemplates } from '@/api';
import type { ApplicationTemplate, ApplicationTemplateField } from '@/types';

// Applicant merge fields available in the backend's
// build_application_merge_context() (backend/app/services/leasing_funnel_service.py).
// Keep this list in sync.
const MERGE_FIELDS = [
  'applicant_name',
  'applicant_first_name',
  'applicant_last_name',
  'applicant_email',
  'applicant_phone',
  'desired_move_in',
  'monthly_income',
  'organization_name',
  'date',
];

const FIELD_TYPES = ['text', 'textarea', 'number', 'date', 'select'];

const ApplicationTemplatesPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [templates, setTemplates] = useState<ApplicationTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ApplicationTemplate | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [body, setBody] = useState('');
  const [fields, setFields] = useState<ApplicationTemplateField[]>([]);
  const [isDefault, setIsDefault] = useState(false);
  const [isActive, setIsActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [drafting, setDrafting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await applicationTemplates.list();
      setTemplates(r.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load application templates.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setName('');
    setDescription('');
    setBody('');
    setFields([]);
    setIsDefault(false);
    setIsActive(true);
    setModalOpen(true);
  };

  const openSample = async () => {
    setDrafting(true);
    try {
      const { data } = await applicationTemplates.getSample();
      setEditing(null);
      setName(data.name);
      setDescription(data.description);
      setBody(data.body);
      setFields(data.field_schema ?? []);
      setIsDefault(false);
      setIsActive(true);
      setModalOpen(true);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load the sample application.' });
    } finally {
      setDrafting(false);
    }
  };

  const openEdit = (t: ApplicationTemplate) => {
    setEditing(t);
    setName(t.name);
    setDescription(t.description ?? '');
    setBody(t.body);
    setFields(t.field_schema ?? []);
    setIsDefault(t.is_default);
    setIsActive(t.is_active);
    setModalOpen(true);
  };

  const updateField = (
    i: number,
    key: keyof ApplicationTemplateField,
    value: string | boolean,
  ) => {
    setFields((prev) => prev.map((f, idx) => (idx === i ? { ...f, [key]: value } : f)));
  };

  const addField = () =>
    setFields((prev) => [...prev, { key: '', label: '', type: 'text', required: false }]);

  const removeField = (i: number) =>
    setFields((prev) => prev.filter((_, idx) => idx !== i));

  const save = async () => {
    if (!name.trim()) {
      addFlash({ type: 'error', content: 'Template name is required.' });
      return;
    }
    if (!body.trim()) {
      addFlash({ type: 'error', content: 'Template body is required.' });
      return;
    }
    const cleanFields = fields
      .filter((f) => f.key.trim())
      .map((f) => ({
        key: f.key.trim(),
        label: f.label.trim() || f.key.trim(),
        type: f.type || 'text',
        required: !!f.required,
      }));
    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        description: description.trim() || null,
        body,
        field_schema: cleanFields,
        is_default: isDefault,
        is_active: isActive,
      };
      if (editing) {
        await applicationTemplates.update(editing.id, payload);
        addFlash({ type: 'success', content: 'Template updated.' });
      } else {
        await applicationTemplates.create(payload);
        addFlash({ type: 'success', content: 'Template created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save template.' });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (t: ApplicationTemplate) => {
    if (!window.confirm(`Delete template "${t.name}"?`)) return;
    try {
      await applicationTemplates.delete(t.id);
      addFlash({ type: 'success', content: 'Template deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete template.' });
    }
  };

  return (
    <SpaceBetween size="l">
      <Table<ApplicationTemplate>
        loading={loading}
        items={templates}
        variant="container"
        header={
          <Header
            counter={`(${templates.length})`}
            description="Reusable residential application documents with merge fields and applicant-filled fields, used to send an application to a prospect."
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={openSample} loading={drafting}>
                  Start from sample application
                </Button>
                <Button variant="primary" onClick={openCreate}>
                  Add template
                </Button>
              </SpaceBetween>
            }
          >
            Application templates
          </Header>
        }
        columnDefinitions={[
          { id: 'name', header: 'Name', cell: (t) => t.name },
          { id: 'description', header: 'Description', cell: (t) => t.description ?? '—' },
          {
            id: 'fields',
            header: 'Fields',
            cell: (t) => (t.field_schema ? t.field_schema.length : 0),
          },
          {
            id: 'default',
            header: 'Default',
            cell: (t) => (t.is_default ? <Badge color="blue">default</Badge> : '—'),
          },
          {
            id: 'active',
            header: 'Status',
            cell: (t) =>
              t.is_active ? (
                <Badge color="green">active</Badge>
              ) : (
                <Badge color="grey">inactive</Badge>
              ),
          },
          {
            id: 'actions',
            header: 'Actions',
            cell: (t) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => openEdit(t)}>
                  Edit
                </Button>
                <Button variant="inline-link" onClick={() => remove(t)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No application templates yet.</Box>}
      />

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        size="large"
        header={editing ? 'Edit template' : 'Add template'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={saving} onClick={save}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Name">
            <Input value={name} onChange={({ detail }) => setName(detail.value)} />
          </FormField>
          <FormField label="Description">
            <Input
              value={description}
              onChange={({ detail }) => setDescription(detail.value)}
            />
          </FormField>
          <FormField
            label="Body"
            description={`Available merge fields (wrap in {{ }}): ${MERGE_FIELDS.join(', ')}`}
          >
            <Textarea
              rows={10}
              value={body}
              onChange={({ detail }) => setBody(detail.value)}
            />
          </FormField>
          <FormField
            label="Applicant fields"
            description="Structured fields the applicant fills in on the application page."
            secondaryControl={<Button onClick={addField}>Add field</Button>}
          >
            <SpaceBetween size="xs">
              {fields.length === 0 && <Box color="text-status-inactive">No fields.</Box>}
              {fields.map((f, i) => (
                <ColumnLayout key={i} columns={4}>
                  <Input
                    placeholder="key"
                    value={f.key}
                    onChange={({ detail }) => updateField(i, 'key', detail.value)}
                  />
                  <Input
                    placeholder="Label"
                    value={f.label}
                    onChange={({ detail }) => updateField(i, 'label', detail.value)}
                  />
                  <Select
                    selectedOption={{ label: f.type || 'text', value: f.type || 'text' }}
                    onChange={({ detail }) =>
                      updateField(i, 'type', detail.selectedOption.value ?? 'text')
                    }
                    options={FIELD_TYPES.map((t) => ({ label: t, value: t }))}
                  />
                  <SpaceBetween direction="horizontal" size="xs">
                    <Checkbox
                      checked={!!f.required}
                      onChange={({ detail }) => updateField(i, 'required', detail.checked)}
                    >
                      Required
                    </Checkbox>
                    <Button variant="inline-link" onClick={() => removeField(i)}>
                      Remove
                    </Button>
                  </SpaceBetween>
                </ColumnLayout>
              ))}
            </SpaceBetween>
          </FormField>
          <FormField label="Default template">
            <Select
              selectedOption={
                isDefault ? { label: 'Yes', value: 'yes' } : { label: 'No', value: 'no' }
              }
              onChange={({ detail }) => setIsDefault(detail.selectedOption.value === 'yes')}
              options={[
                { label: 'No', value: 'no' },
                { label: 'Yes', value: 'yes' },
              ]}
            />
          </FormField>
          <FormField label="Active">
            <Select
              selectedOption={
                isActive
                  ? { label: 'Active', value: 'yes' }
                  : { label: 'Inactive', value: 'no' }
              }
              onChange={({ detail }) => setIsActive(detail.selectedOption.value === 'yes')}
              options={[
                { label: 'Active', value: 'yes' },
                { label: 'Inactive', value: 'no' },
              ]}
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default ApplicationTemplatesPage;
