import React, { useEffect, useState, useCallback } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import Table from '@cloudscape-design/components/table';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import Select from '@cloudscape-design/components/select';
import Modal from '@cloudscape-design/components/modal';
import {
  trash as trashApi,
  offices as officesApi,
  leases as leasesApi,
  landlords as landlordsApi,
  vendors as vendorsApi,
  transitions as transitionsApi,
  hvacContracts as hvacContractsApi,
  maintenanceTickets as ticketsApi,
  type TrashItem,
} from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';

type SelectOption = { label: string; value: string };

const ENTITY_OPTIONS: SelectOption[] = [
  { label: 'Office', value: 'office' },
  { label: 'Lease', value: 'lease' },
  { label: 'Landlord', value: 'landlord' },
  { label: 'Vendor', value: 'vendor' },
  { label: 'Transition', value: 'transition' },
  { label: 'HVAC Contract', value: 'hvac_contract' },
  { label: 'Maintenance Ticket', value: 'maintenance_ticket' },
];

// Map entity_type -> restore() function. Each entity exposes its own
// PATCH /{entity}/{id}/restore endpoint already.
const RESTORE_FNS: Record<string, (id: string) => Promise<unknown>> = {
  office: (id) => officesApi.restore(id),
  lease: (id) => leasesApi.restore(id),
  landlord: (id) => landlordsApi.restore(id),
  vendor: (id) => vendorsApi.restore(id),
  transition: (id) => transitionsApi.restore(id),
  hvac_contract: (id) => hvacContractsApi.restore(id),
  maintenance_ticket: (id) => ticketsApi.restore(id),
};

const TrashPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [entityType, setEntityType] = useState<SelectOption>(ENTITY_OPTIONS[0]);
  const [items, setItems] = useState<TrashItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmPermanent, setConfirmPermanent] = useState<TrashItem | null>(null);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await trashApi.summary();
      setCounts(res.data.counts);
    } catch {
      // Non-fatal
    }
  }, []);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await trashApi.list(entityType.value);
      setItems(res.data.items);
    } catch {
      setError('Failed to load trash.');
    } finally {
      setLoading(false);
    }
  }, [entityType]);

  useEffect(() => {
    fetchSummary();
    fetchItems();
  }, [fetchSummary, fetchItems]);

  const handleRestore = async (item: TrashItem) => {
    const restoreFn = RESTORE_FNS[item.entity_type];
    if (!restoreFn) return;
    setBusyId(item.id);
    setError(null);
    try {
      await restoreFn(item.id);
      addFlash({ type: 'success', content: `Restored "${item.label}".` });
      await Promise.all([fetchSummary(), fetchItems()]);
    } catch {
      setError(`Failed to restore "${item.label}".`);
    } finally {
      setBusyId(null);
    }
  };

  const handlePermanentDelete = async (item: TrashItem) => {
    setConfirmPermanent(null);
    setBusyId(item.id);
    setError(null);
    try {
      await trashApi.permanentDelete(item.entity_type, item.id);
      addFlash({ type: 'success', content: `Permanently deleted "${item.label}".` });
      await Promise.all([fetchSummary(), fetchItems()]);
    } catch {
      setError(`Failed to permanently delete "${item.label}".`);
    } finally {
      setBusyId(null);
    }
  };

  const columnDefinitions = [
    { id: 'label', header: 'Label', cell: (item: TrashItem) => item.label },
    {
      id: 'deleted_at',
      header: 'Deleted',
      cell: (item: TrashItem) =>
        item.deleted_at ? new Date(item.deleted_at).toLocaleString() : '—',
      width: 220,
    },
    {
      id: 'actions',
      header: '',
      cell: (item: TrashItem) => (
        <SpaceBetween direction="horizontal" size="xs">
          <Button
            iconName="undo"
            loading={busyId === item.id}
            onClick={() => handleRestore(item)}
          >
            Restore
          </Button>
          <Button
            iconName="remove"
            disabled={busyId === item.id}
            onClick={() => setConfirmPermanent(item)}
          >
            Delete forever
          </Button>
        </SpaceBetween>
      ),
      width: 260,
    },
  ];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Soft-deleted records that can be restored or permanently removed."
        >
          Trash
        </Header>
      }
    >
      <SpaceBetween size="m">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Container header={<Header variant="h2">Summary</Header>}>
          <SpaceBetween direction="horizontal" size="m">
            {ENTITY_OPTIONS.map((opt) => (
              <Box key={opt.value} variant="awsui-key-label">
                {opt.label}: <strong>{counts[opt.value] ?? 0}</strong>
              </Box>
            ))}
          </SpaceBetween>
        </Container>

        <Container header={<Header variant="h2">Browse by type</Header>}>
          <SpaceBetween size="m">
            <Select
              selectedOption={entityType}
              onChange={({ detail }) => setEntityType(detail.selectedOption as SelectOption)}
              options={ENTITY_OPTIONS}
            />

            <Table
              columnDefinitions={columnDefinitions}
              items={items}
              loading={loading}
              loadingText="Loading deleted records..."
              empty={
                <Box textAlign="center" color="inherit" padding="l">
                  No deleted {entityType.label.toLowerCase()} records.
                </Box>
              }
              header={<Header counter={`(${items.length})`}>{entityType.label}</Header>}
            />
          </SpaceBetween>
        </Container>
      </SpaceBetween>

      <Modal
        visible={!!confirmPermanent}
        onDismiss={() => setConfirmPermanent(null)}
        header="Permanently delete"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setConfirmPermanent(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => confirmPermanent && handlePermanentDelete(confirmPermanent)}
              >
                Delete forever
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        Are you sure you want to permanently delete{' '}
        <strong>{confirmPermanent?.label}</strong>? This cannot be undone.
      </Modal>
    </ContentLayout>
  );
};

export default TrashPage;
