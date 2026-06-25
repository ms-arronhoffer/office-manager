import React, { useEffect, useState, useCallback } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Toggle from '@cloudscape-design/components/toggle';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import { useNavigate } from 'react-router-dom';
import { wizardConfigs as wizardApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type { WizardConfig } from '@/types';

interface FormState {
  name: string;
  description: string;
  stepsJson: string;
  is_active: boolean;
  is_default: boolean;
}

const emptyForm: FormState = {
  name: '',
  description: '',
  stepsJson: '[\n  \n]',
  is_active: true,
  is_default: false,
};

const WizardConfigsPage: React.FC = () => {
  const navigate = useNavigate();
  const { addFlash } = useFlashbar();

  const [configs, setConfigs] = useState<WizardConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const fetchConfigs = useCallback(async () => {
    try {
      const res = await wizardApi.list();
      setConfigs(res.data as unknown as WizardConfig[]);
    } catch {
      setError('Failed to load wizard configurations.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfigs();
  }, [fetchConfigs]);

  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm);
    setFormError(null);
    setJsonError(null);
    setModalVisible(true);
  };

  const openEdit = (config: WizardConfig) => {
    setEditingId(config.id);
    setForm({
      name: config.name,
      description: config.description ?? '',
      stepsJson: JSON.stringify(config.steps, null, 2),
      is_active: config.is_active,
      is_default: config.is_default,
    });
    setFormError(null);
    setJsonError(null);
    setModalVisible(true);
  };

  const validateJson = (json: string): boolean => {
    try {
      const parsed = JSON.parse(json);
      if (!Array.isArray(parsed)) {
        setJsonError('Steps must be a JSON array.');
        return false;
      }
      setJsonError(null);
      return true;
    } catch (e) {
      setJsonError(`Invalid JSON: ${(e as Error).message}`);
      return false;
    }
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError('Name is required.');
      return;
    }
    if (!validateJson(form.stepsJson)) return;

    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        steps: JSON.parse(form.stepsJson),
        is_active: form.is_active,
        is_default: form.is_default,
      };

      if (editingId) {
        await wizardApi.update(editingId, payload);
        addFlash({ type: 'success', content: `Updated "${payload.name}".` });
      } else {
        await wizardApi.create(payload);
        addFlash({ type: 'success', content: `Created "${payload.name}".` });
      }
      setModalVisible(false);
      await fetchConfigs();
    } catch {
      setFormError('Failed to save configuration.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (config: WizardConfig) => {
    try {
      await wizardApi.delete(config.id);
      addFlash({ type: 'success', content: `Deleted "${config.name}".` });
      await fetchConfigs();
    } catch {
      addFlash({ type: 'error', content: `Failed to delete "${config.name}".` });
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
    <>
      <ContentLayout
        header={
          <SpaceBetween size="m">
            <BreadcrumbGroup
              items={[
                { text: 'Home', href: '/' },
                { text: 'Wizard Configs', href: '/wizard-configs' },
              ]}
              onFollow={(e) => {
                e.preventDefault();
                navigate(e.detail.href);
              }}
            />
            <Header
              variant="h1"
              counter={`(${configs.length})`}
              actions={
                <Button variant="primary" onClick={openCreate}>
                  Create Configuration
                </Button>
              }
            >
              Wizard Configurations
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

          <Table<WizardConfig>
            columnDefinitions={[
              {
                id: 'name',
                header: 'Name',
                cell: (item) => (
                  <Button variant="link" onClick={() => openEdit(item)}>
                    {item.name}
                  </Button>
                ),
                sortingField: 'name',
              },
              {
                id: 'description',
                header: 'Description',
                cell: (item) => item.description || '—',
              },
              {
                id: 'steps',
                header: 'Steps',
                cell: (item) => item.steps.length,
              },
              {
                id: 'is_active',
                header: 'Active',
                cell: (item) => (
                  <StatusIndicator type={item.is_active ? 'success' : 'stopped'}>
                    {item.is_active ? 'Yes' : 'No'}
                  </StatusIndicator>
                ),
              },
              {
                id: 'is_default',
                header: 'Default',
                cell: (item) => (
                  <StatusIndicator type={item.is_default ? 'success' : 'stopped'}>
                    {item.is_default ? 'Yes' : 'No'}
                  </StatusIndicator>
                ),
              },
              {
                id: 'updated_at',
                header: 'Last Updated',
                cell: (item) => new Date(item.updated_at).toLocaleString(),
              },
              {
                id: 'actions',
                header: '',
                cell: (item) => (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={() => openEdit(item)} iconName="edit" variant="inline-icon" ariaLabel="Edit" />
                    <Button onClick={() => handleDelete(item)} iconName="remove" variant="inline-icon" ariaLabel="Delete" />
                  </SpaceBetween>
                ),
              },
            ]}
            items={configs}
            empty={
              <Box textAlign="center" color="inherit" padding="l">
                No wizard configurations. Create one to get started.
              </Box>
            }
          />
        </SpaceBetween>
      </ContentLayout>

      {/* Create / Edit Modal */}
      <Modal
        visible={modalVisible}
        onDismiss={() => setModalVisible(false)}
        header={editingId ? 'Edit Configuration' : 'Create Configuration'}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setModalVisible(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleSave} loading={saving}>
                {editingId ? 'Save Changes' : 'Create'}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {formError && (
            <Alert type="error" dismissible onDismiss={() => setFormError(null)}>
              {formError}
            </Alert>
          )}

          <FormField label="Name" constraintText="Required">
            <Input
              value={form.name}
              onChange={({ detail }) => setForm((f) => ({ ...f, name: detail.value }))}
              placeholder="e.g., Default Maintenance Request"
            />
          </FormField>

          <FormField label="Description">
            <Input
              value={form.description}
              onChange={({ detail }) => setForm((f) => ({ ...f, description: detail.value }))}
              placeholder="Brief description of this wizard flow"
            />
          </FormField>

          <SpaceBetween direction="horizontal" size="l">
            <Toggle
              checked={form.is_active}
              onChange={({ detail }) => setForm((f) => ({ ...f, is_active: detail.checked }))}
            >
              Active
            </Toggle>
            <Toggle
              checked={form.is_default}
              onChange={({ detail }) => setForm((f) => ({ ...f, is_default: detail.checked }))}
            >
              Default
            </Toggle>
          </SpaceBetween>

          <FormField
            label="Steps (JSON)"
            errorText={jsonError}
            constraintText="JSON array of step objects. Each step needs: id, type, text. Optional: field, options, next."
          >
            <Textarea
              value={form.stepsJson}
              onChange={({ detail }) => {
                setForm((f) => ({ ...f, stepsJson: detail.value }));
                if (jsonError) validateJson(detail.value);
              }}
              rows={20}
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
};

export default WizardConfigsPage;
