import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Table from '@cloudscape-design/components/table';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Link from '@cloudscape-design/components/link';
import { dashboard as dashboardApi, offices as officesApi, space as spaceApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import type { SpaceUtilizationRow, Office } from '@/types';

const fmtSqft = (n: number | null | undefined) =>
  n == null ? '—' : `${n.toLocaleString(undefined, { maximumFractionDigits: 0 })} sqft`;

const SpacePage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [spaceUtil, setSpaceUtil] = useState<SpaceUtilizationRow[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showModal, setShowModal] = useState(false);
  const [selectedOfficeId, setSelectedOfficeId] = useState<string | null>(null);
  const [snapshotForm, setSnapshotForm] = useState({
    current_headcount: '',
    notes: '',
    snapshot_date: new Date().toISOString().slice(0, 16),
  });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [utilRes, officesRes] = await Promise.all([
        dashboardApi.getSpaceUtilization(),
        officesApi.list({ page_size: 1000 }),
      ]);
      setSpaceUtil(utilRes.data);
      setOffices(officesRes.data.items);
    } catch {
      setError('Failed to load space data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openSnapshot = (officeId: string) => {
    const office = offices.find(o => o.id === officeId);
    setSelectedOfficeId(officeId);
    setSnapshotForm({
      current_headcount: String(office?.current_headcount ?? ''),
      notes: '',
      snapshot_date: new Date().toISOString().slice(0, 16),
    });
    setShowModal(true);
  };

  const handleSaveSnapshot = async () => {
    if (!selectedOfficeId) return;
    setSaving(true);
    try {
      await spaceApi.createSnapshot(selectedOfficeId, {
        snapshot_date: snapshotForm.snapshot_date
          ? new Date(snapshotForm.snapshot_date).toISOString()
          : undefined,
        current_headcount: snapshotForm.current_headcount
          ? Number(snapshotForm.current_headcount)
          : undefined,
        notes: snapshotForm.notes || undefined,
      });
      addFlash({ type: 'success', content: 'Snapshot recorded.' });
      setShowModal(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save snapshot.' });
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

  const totalSqft = spaceUtil.reduce((s, r) => s + (r.total_sqft ?? 0), 0);
  const totalHeadcount = spaceUtil.reduce((s, r) => s + (r.current_headcount ?? 0), 0);
  const tracked = spaceUtil.filter(r => r.occupancy_pct != null);
  const avgOccupancy = tracked.length
    ? tracked.reduce((s, r) => s + (r.occupancy_pct ?? 0), 0) / tracked.length
    : null;

  const selectedOffice = offices.find(o => o.id === selectedOfficeId);

  return (
    <>
      <ContentLayout
        header={
          <Header
            variant="h1"
            description="Portfolio-wide space and occupancy tracking. Record periodic headcount snapshots to track utilization trends."
          >
            Space &amp; Occupancy Management
          </Header>
        }
      >
        <SpaceBetween size="l">
          {error && <Alert type="error">{error}</Alert>}

          {/* KPI Summary */}
          <Container>
            <ColumnLayout columns={4}>
              <Box textAlign="center" padding="s">
                <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">TOTAL PORTFOLIO SQFT</Box>
                <Box fontSize="heading-xl" fontWeight="bold">{fmtSqft(totalSqft || null)}</Box>
              </Box>
              <Box textAlign="center" padding="s">
                <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">TOTAL HEADCOUNT</Box>
                <Box fontSize="heading-xl" fontWeight="bold">{totalHeadcount || '—'}</Box>
              </Box>
              <Box textAlign="center" padding="s">
                <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">AVG OCCUPANCY</Box>
                <Box fontSize="heading-xl" fontWeight="bold">
                  {avgOccupancy != null ? `${avgOccupancy.toFixed(1)}%` : '—'}
                </Box>
              </Box>
              <Box textAlign="center" padding="s">
                <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">OFFICES WITH SPACE DATA</Box>
                <Box fontSize="heading-xl" fontWeight="bold">
                  {spaceUtil.filter(r => r.total_sqft).length} / {spaceUtil.length}
                </Box>
              </Box>
            </ColumnLayout>
          </Container>

          {/* Per-office table */}
          <Container
            header={
              <Header
                variant="h2"
                description="Click an office name to view its full space history and trend charts."
              >
                Office Space Overview
              </Header>
            }
          >
            <Table
              items={spaceUtil}
              columnDefinitions={[
                {
                  id: 'office',
                  header: 'Office',
                  cell: (r: SpaceUtilizationRow) => (
                    <Link onFollow={() => navigate(`/offices/${r.office_id}`)}>
                      {r.office_number ? `#${r.office_number} — ${r.office_name}` : r.office_name}
                    </Link>
                  ),
                },
                {
                  id: 'sqft',
                  header: 'Total Sqft',
                  cell: (r: SpaceUtilizationRow) => fmtSqft(r.total_sqft),
                },
                {
                  id: 'usable',
                  header: 'Usable Sqft',
                  cell: (r: SpaceUtilizationRow) => fmtSqft(r.usable_sqft),
                },
                {
                  id: 'headcount',
                  header: 'Headcount',
                  cell: (r: SpaceUtilizationRow) =>
                    r.current_headcount != null
                      ? `${r.current_headcount} / ${r.headcount_capacity ?? '?'}`
                      : '—',
                },
                {
                  id: 'occupancy',
                  header: 'Occupancy',
                  cell: (r: SpaceUtilizationRow) =>
                    r.occupancy_pct != null ? (
                      <ProgressBar
                        value={r.occupancy_pct}
                        additionalInfo={`${r.occupancy_pct}%`}
                        status={r.occupancy_pct > 90 ? 'error' : r.occupancy_pct > 75 ? 'in-progress' : 'success'}
                      />
                    ) : '—',
                },
                {
                  id: 'spp',
                  header: 'Sqft / Person',
                  cell: (r: SpaceUtilizationRow) =>
                    r.sqft_per_person != null ? `${r.sqft_per_person}` : '—',
                },
                ...(canEdit ? [{
                  id: 'actions',
                  header: '',
                  cell: (r: SpaceUtilizationRow) => (
                    <Button
                      variant="inline-link"
                      onClick={() => openSnapshot(r.office_id)}
                    >
                      Record Snapshot
                    </Button>
                  ),
                  width: 140,
                }] : []),
              ]}
              empty={
                <Box textAlign="center" color="inherit" padding="l">
                  <SpaceBetween size="m">
                    <b>No offices with space data</b>
                    <Box color="text-body-secondary">
                      Add total sqft and headcount capacity to your office records to begin tracking space utilization.
                    </Box>
                    <Button onClick={() => navigate('/offices')}>Go to Offices</Button>
                  </SpaceBetween>
                </Box>
              }
            />
          </Container>
        </SpaceBetween>
      </ContentLayout>

      {/* Record Snapshot Modal */}
      <Modal
        visible={showModal}
        onDismiss={() => setShowModal(false)}
        header={`Record Snapshot — ${selectedOffice ? (selectedOffice.office_number ? `#${selectedOffice.office_number} ${selectedOffice.location_name}` : selectedOffice.location_name) : ''}`}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowModal(false)}>Cancel</Button>
              <Button variant="primary" loading={saving} onClick={handleSaveSnapshot}>
                Record Snapshot
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Snapshot Date">
            <Input
              type="datetime-local"
              value={snapshotForm.snapshot_date}
              onChange={({ detail }) =>
                setSnapshotForm(prev => ({ ...prev, snapshot_date: detail.value }))
              }
            />
          </FormField>
          <FormField
            label="Current Headcount"
            constraintText="Leave blank to use the office's current headcount value"
          >
            <Input
              type="number"
              value={snapshotForm.current_headcount}
              onChange={({ detail }) =>
                setSnapshotForm(prev => ({ ...prev, current_headcount: detail.value }))
              }
              placeholder={String(selectedOffice?.current_headcount ?? 'e.g. 45')}
            />
          </FormField>
          <FormField label="Notes" constraintText="Optional">
            <Input
              value={snapshotForm.notes}
              onChange={({ detail }) =>
                setSnapshotForm(prev => ({ ...prev, notes: detail.value }))
              }
              placeholder="Any context about this snapshot"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
};

export default SpacePage;
