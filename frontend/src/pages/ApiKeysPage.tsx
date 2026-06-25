import React, { useEffect, useState } from 'react';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Checkbox from '@cloudscape-design/components/checkbox';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ContentLayout from '@cloudscape-design/components/content-layout';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import Modal from '@cloudscape-design/components/modal';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';
import { apiKeys as apiKeysApi } from '@/api';
import type { ApiKey } from '@/types';

const AVAILABLE_SCOPES = [
  { value: 'read:all', label: 'Read — all resources' },
  { value: 'write:tickets', label: 'Write — maintenance tickets' },
  { value: 'write:leases', label: 'Write — leases' },
  { value: 'write:all', label: 'Write — all resources (full access)' },
];

const ApiKeysPage: React.FC = () => {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newKey, setNewKey] = useState<string | null>(null);

  // Create modal state
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newScopes, setNewScopes] = useState<Set<string>>(new Set(['read:all']));
  const [expiresInDays, setExpiresInDays] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiKeysApi.list();
      setKeys(data);
    } catch {
      setError('Could not load API keys.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    if (!newName.trim()) {
      setCreateError('Name is required.');
      return;
    }
    setIsCreating(true);
    setCreateError(null);
    try {
      const { data } = await apiKeysApi.create({
        name: newName.trim(),
        scopes: Array.from(newScopes),
        expires_in_days: expiresInDays ? parseInt(expiresInDays, 10) : undefined,
      });
      setNewKey(data.key);
      setShowCreate(false);
      setNewName('');
      setNewScopes(new Set(['read:all']));
      setExpiresInDays('');
      await load();
    } catch {
      setCreateError('Could not create API key.');
    } finally {
      setIsCreating(false);
    }
  };

  const handleRevoke = async (id: string) => {
    setDeletingId(id);
    try {
      await apiKeysApi.revoke(id);
      setKeys(prev => prev.filter(k => k.id !== id));
    } catch {
      setError('Could not revoke API key.');
    } finally {
      setDeletingId(null);
    }
  };

  const toggleScope = (scope: string) => {
    setNewScopes(prev => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  };

  if (isLoading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="API keys allow external systems to authenticate with your organization's data."
          actions={
            <Button variant="primary" onClick={() => setShowCreate(true)} iconName="add-plus">
              Create API key
            </Button>
          }
        >
          API Keys
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        {newKey && (
          <Alert
            type="success"
            dismissible
            onDismiss={() => setNewKey(null)}
            header="API key created — copy it now"
          >
            <Box variant="p">
              This key will <strong>never be shown again</strong>. Copy it and store it securely.
            </Box>
            <Box>
              <code style={{ wordBreak: 'break-all', fontSize: 13 }}>{newKey}</code>
            </Box>
          </Alert>
        )}

        <Container>
          <Table
            items={keys}
            empty={
              <Box textAlign="center" color="inherit">
                <Box variant="strong">No API keys</Box>
                <Box variant="p" color="inherit">
                  Create an API key to allow external systems to access this organization.
                </Box>
              </Box>
            }
            columnDefinitions={[
              {
                id: 'name',
                header: 'Name',
                cell: item => item.name,
              },
              {
                id: 'prefix',
                header: 'Key prefix',
                cell: item => (
                  <code style={{ fontSize: 13 }}>om_{item.key_prefix}_***</code>
                ),
              },
              {
                id: 'scopes',
                header: 'Scopes',
                cell: item => (
                  <SpaceBetween direction="horizontal" size="xxs">
                    {item.scopes.map(s => (
                      <Badge key={s} color="blue">{s}</Badge>
                    ))}
                  </SpaceBetween>
                ),
              },
              {
                id: 'status',
                header: 'Status',
                cell: item => (
                  <Badge color={item.is_active ? 'green' : 'red'}>
                    {item.is_active ? 'Active' : 'Revoked'}
                  </Badge>
                ),
              },
              {
                id: 'last_used',
                header: 'Last used',
                cell: item => item.last_used_at
                  ? new Date(item.last_used_at).toLocaleString()
                  : 'Never',
              },
              {
                id: 'expires',
                header: 'Expires',
                cell: item => item.expires_at
                  ? new Date(item.expires_at).toLocaleDateString()
                  : 'Never',
              },
              {
                id: 'actions',
                header: '',
                cell: item => (
                  <Button
                    variant="link"
                    loading={deletingId === item.id}
                    onClick={() => handleRevoke(item.id)}
                  >
                    Revoke
                  </Button>
                ),
              },
            ]}
          />
        </Container>
      </SpaceBetween>

      {/* Create modal */}
      <Modal
        visible={showCreate}
        onDismiss={() => { setShowCreate(false); setCreateError(null); }}
        header="Create API key"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowCreate(false)}>Cancel</Button>
              <Button variant="primary" loading={isCreating} onClick={handleCreate}>
                Create key
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {createError && <Alert type="error">{createError}</Alert>}
          <FormField label="Key name" constraintText="Describe what this key is used for.">
            <Input
              value={newName}
              onChange={({ detail }) => setNewName(detail.value)}
              placeholder="e.g. CI/CD pipeline"
              disabled={isCreating}
            />
          </FormField>
          <FormField label="Scopes">
            <SpaceBetween size="xs">
              {AVAILABLE_SCOPES.map(s => (
                <Checkbox
                  key={s.value}
                  checked={newScopes.has(s.value)}
                  onChange={() => toggleScope(s.value)}
                  disabled={isCreating}
                >
                  {s.label}
                </Checkbox>
              ))}
            </SpaceBetween>
          </FormField>
          <FormField
            label="Expires in (days)"
            constraintText="Leave blank for a key that never expires."
          >
            <Input
              type="number"
              value={expiresInDays}
              onChange={({ detail }) => setExpiresInDays(detail.value)}
              placeholder="e.g. 365"
              disabled={isCreating}
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default ApiKeysPage;
