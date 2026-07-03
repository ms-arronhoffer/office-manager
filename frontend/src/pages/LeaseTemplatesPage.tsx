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
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import { useFlashbar } from '@/context/FlashbarContext';
import { leaseTemplates } from '@/api';
import type { LeaseTemplate } from '@/types';

const MERGE_FIELDS = [
  'tenant_name',
  'tenant_names',
  'unit_number',
  'unit_name',
  'property_address',
  'rent_amount',
  'rent_frequency',
  'security_deposit',
  'pet_deposit',
  'lease_start',
  'lease_end',
  'lease_type',
  'organization_name',
  'date',
];

const LeaseTemplatesPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [templates, setTemplates] = useState<LeaseTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<LeaseTemplate | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [body, setBody] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [isActive, setIsActive] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await leaseTemplates.list();
      setTemplates(r.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load lease templates.' });
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
    setIsDefault(false);
    setIsActive(true);
    setModalOpen(true);
  };

  const openEdit = (t: LeaseTemplate) => {
    setEditing(t);
    setName(t.name);
    setDescription(t.description ?? '');
    setBody(t.body);
    setIsDefault(t.is_default);
    setIsActive(t.is_active);
    setModalOpen(true);
  };

  const save = async () => {
    if (!name.trim()) {
      addFlash({ type: 'error', content: 'Template name is required.' });
      return;
    }
    if (!body.trim()) {
      addFlash({ type: 'error', content: 'Template body is required.' });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: name.trim(),
        description: description.trim() || null,
        body,
        is_default: isDefault,
        is_active: isActive,
      };
      if (editing) {
        await leaseTemplates.update(editing.id, payload);
        addFlash({ type: 'success', content: 'Template updated.' });
      } else {
        await leaseTemplates.create(payload);
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

  const remove = async (t: LeaseTemplate) => {
    if (!window.confirm(`Delete template "${t.name}"?`)) return;
    try {
      await leaseTemplates.delete(t.id);
      addFlash({ type: 'success', content: 'Template deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete template.' });
    }
  };

  return (
    <SpaceBetween size="l">
      <Table<LeaseTemplate>
        loading={loading}
        items={templates}
        variant="container"
        header={
          <Header
            counter={`(${templates.length})`}
            description="Reusable lease documents with merge fields, used to generate e-signature requests."
            actions={
              <Button variant="primary" onClick={openCreate}>
                Add template
              </Button>
            }
          >
            Lease templates
          </Header>
        }
        columnDefinitions={[
          { id: 'name', header: 'Name', cell: (t) => t.name },
          { id: 'description', header: 'Description', cell: (t) => t.description ?? '—' },
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
        empty={<Box textAlign="center">No lease templates yet.</Box>}
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
              rows={12}
              value={body}
              onChange={({ detail }) => setBody(detail.value)}
            />
          </FormField>
          <FormField label="Default template">
            <Select
              selectedOption={
                isDefault
                  ? { label: 'Yes', value: 'yes' }
                  : { label: 'No', value: 'no' }
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

export default LeaseTemplatesPage;
