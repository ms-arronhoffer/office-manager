import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Tabs from '@cloudscape-design/components/tabs';
import Table from '@cloudscape-design/components/table';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BarChart from '@cloudscape-design/components/bar-chart';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Link from '@cloudscape-design/components/link';
import { offices as officesApi, leases as leasesApi, landlords as landlordsApi, hvacContracts as hvacContractsApi, maintenanceTickets as ticketsApi, transitions as transitionsApi, space as spaceApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import { formatAddress } from '@/components/common/AddressFields';
import ActivityTimeline from '@/components/common/ActivityTimeline';
import type { Office, Lease, Landlord, LandlordContact, HvacContract, MaintenanceTicket, Transition, SpaceSnapshot } from '@/types';

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value ?? '—'}</Box>
  </div>
);

const OfficeDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();

  const [office, setOffice] = useState<Office | null>(null);
  const [leases, setLeases] = useState<Lease[]>([]);
  const [officeLandlords, setOfficeLandlords] = useState<Landlord[]>([]);
  const [landlordsLoading, setLandlordsLoading] = useState(false);
  const [hvacContracts, setHvacContracts] = useState<HvacContract[]>([]);
  const [tickets, setTickets] = useState<MaintenanceTicket[]>([]);
  const [officeTransitions, setOfficeTransitions] = useState<Transition[]>([]);
  const [loading, setLoading] = useState(true);
  const [leasesLoading, setLeasesLoading] = useState(false);
  const [hvacLoading, setHvacLoading] = useState(false);
  const [ticketsLoading, setTicketsLoading] = useState(false);
  const [transitionsLoading, setTransitionsLoading] = useState(false);
  const [spaceHistory, setSpaceHistory] = useState<SpaceSnapshot[]>([]);
  const [spaceHistoryLoading, setSpaceHistoryLoading] = useState(false);
  const [showSnapshotModal, setShowSnapshotModal] = useState(false);
  const [snapshotForm, setSnapshotForm] = useState({ current_headcount: '', notes: '', snapshot_date: '' });
  const [savingSnapshot, setSavingSnapshot] = useState(false);
  const [deletingSnapshotId, setDeletingSnapshotId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchOffice = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const res = await officesApi.get(id);
      setOffice(res.data);
    } catch {
      setError('Failed to load office details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchLeases = useCallback(async () => {
    if (!id) return;
    setLeasesLoading(true);
    try {
      const res = await leasesApi.list({ page_size: 1000 });
      setLeases(res.data.items.filter((l) => l.office_id === id));
    } catch {
      // non-critical — tab will show empty state
    } finally {
      setLeasesLoading(false);
    }
  }, [id]);

  const fetchLandlords = useCallback(async () => {
    if (!id) return;
    setLandlordsLoading(true);
    try {
      const res = await landlordsApi.list({ office_id: id, page_size: 1000 });
      setOfficeLandlords(res.data.items);
    } catch {
      // non-critical — tab will fall back to lease-derived landlord
    } finally {
      setLandlordsLoading(false);
    }
  }, [id]);

  const fetchHvacContracts = useCallback(async () => {
    if (!id) return;
    setHvacLoading(true);
    try {
      const res = await hvacContractsApi.list({ page_size: 1000 });
      setHvacContracts(res.data.items);
    } catch {
      // non-critical
    } finally {
      setHvacLoading(false);
    }
  }, [id]);

  const fetchTickets = useCallback(async () => {
    if (!id) return;
    setTicketsLoading(true);
    try {
      const res = await ticketsApi.list({ page_size: 1000 });
      setTickets(res.data.items.filter((t) => t.office_id === id));
    } catch {
      // non-critical
    } finally {
      setTicketsLoading(false);
    }
  }, [id]);

  const fetchTransitions = useCallback(async () => {
    if (!id) return;
    setTransitionsLoading(true);
    try {
      const res = await transitionsApi.list({ page_size: 1000 });
      setOfficeTransitions(res.data.items.filter((t) => t.office_id === id));
    } catch {
      // non-critical
    } finally {
      setTransitionsLoading(false);
    }
  }, [id]);

  const fetchSpaceHistory = useCallback(async () => {
    if (!id) return;
    setSpaceHistoryLoading(true);
    try {
      const res = await spaceApi.listHistory(id);
      setSpaceHistory(res.data);
    } catch {
      // non-critical
    } finally {
      setSpaceHistoryLoading(false);
    }
  }, [id]);

  const handleSaveSnapshot = async () => {
    if (!id) return;
    setSavingSnapshot(true);
    try {
      await spaceApi.createSnapshot(id, {
        snapshot_date: snapshotForm.snapshot_date
          ? new Date(snapshotForm.snapshot_date).toISOString()
          : undefined,
        current_headcount: snapshotForm.current_headcount
          ? Number(snapshotForm.current_headcount)
          : undefined,
        notes: snapshotForm.notes || undefined,
      });
      setShowSnapshotModal(false);
      await fetchSpaceHistory();
    } catch {
      setError('Failed to save snapshot.');
    } finally {
      setSavingSnapshot(false);
    }
  };

  const handleDeleteSnapshot = async (snapId: string) => {
    if (!id) return;
    setDeletingSnapshotId(snapId);
    try {
      await spaceApi.deleteSnapshot(id, snapId);
      await fetchSpaceHistory();
    } catch {
      setError('Failed to delete snapshot.');
    } finally {
      setDeletingSnapshotId(null);
    }
  };

  useEffect(() => {
    fetchOffice();
    fetchLeases();
    fetchLandlords();
    fetchHvacContracts();
    fetchTickets();
    fetchTransitions();
    fetchSpaceHistory();
  }, [fetchOffice, fetchLeases, fetchLandlords, fetchHvacContracts, fetchTickets, fetchTransitions, fetchSpaceHistory]);

  const handleDelete = async () => {
    if (!id || !office) return;
    try {
      await officesApi.delete(id);
      const label = office.location_name;
      navigate('/offices');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button variant="link" onClick={async () => {
              try {
                await officesApi.restore(id);
                navigate(`/offices/${id}`);
              } catch {
                addFlash({ type: 'error', content: 'Failed to undo delete.' });
              }
            }}>Undo</Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete office.');
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (!office) {
    return <Alert type="error">{error || 'Office not found.'}</Alert>;
  }

  // Derive primary landlord from the first lease that has one
  const primaryLandlord = leases.find((l) => l.landlord)?.landlord;

  return (
    <>
      {deleteModal}
      <ContentLayout
        header={
          <SpaceBetween size="m">
            <BreadcrumbGroup
              items={[
                { text: 'Offices', href: '/offices' },
                { text: office.location_name, href: `/offices/${id}` },
              ]}
              onFollow={(e) => {
                e.preventDefault();
                navigate(e.detail.href);
              }}
            />
            <Header
              variant="h1"
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button onClick={() => navigate(`/offices/${id}/edit`)}>Edit</Button>
                  <Button onClick={() => confirmDelete({ itemName: office.location_name, onConfirm: handleDelete })}>Delete</Button>
                </SpaceBetween>
              }
            >
              {office.location_name}
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

          {/* ── Office Information ─────────────────────────────────────────────── */}
          <Container header={<Header variant="h2">Office Information</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <ValuePair label="Office Number" value={office.office_number} />
              <ValuePair label="Location Name" value={office.location_name} />
              <ValuePair label="Type" value={office.office_type} />
              <ValuePair label="Sector" value={office.sector} />
              <ValuePair label="Region" value={office.region} />
              <ValuePair
                label="Status"
                value={
                  <StatusIndicator type={office.is_active ? 'success' : 'stopped'}>
                    {office.is_active ? 'Active' : 'Inactive'}
                  </StatusIndicator>
                }
              />
              <ValuePair
                label="Address"
                value={
                  <span style={{ whiteSpace: 'pre-line' }}>
                    {formatAddress({
                      address_line_1: office.address_line_1,
                      address_line_2: office.address_line_2,
                      city: office.city,
                      state: office.state,
                      zip_code: office.zip_code,
                    }) || '—'}
                  </span>
                }
              />
              <ValuePair label="Phone" value={office.phone_number} />
              <ValuePair label="Fax" value={office.fax} />
              <ValuePair label="Manager" value={office.manager?.name} />
            </ColumnLayout>
            {office.notes && (
              <Box margin={{ top: 'm' }}>
                <Box variant="awsui-key-label">Notes</Box>
                <Box>{office.notes}</Box>
              </Box>
            )}
          </Container>

          {/* ── Space & Occupancy ─────────────────────────────────────────────── */}
          {(office.total_sqft || office.headcount_capacity) && (
            <Container header={<Header variant="h2">Space &amp; Occupancy</Header>}>
              <ColumnLayout columns={3} variant="text-grid">
                <ValuePair
                  label="Total Sq Ft"
                  value={office.total_sqft != null ? `${Number(office.total_sqft).toLocaleString()} sqft` : undefined}
                />
                <ValuePair
                  label="Usable Sq Ft"
                  value={office.usable_sqft != null ? `${Number(office.usable_sqft).toLocaleString()} sqft` : undefined}
                />
                <ValuePair
                  label="Utilization"
                  value={
                    office.total_sqft && office.usable_sqft
                      ? `${Math.round((Number(office.usable_sqft) / Number(office.total_sqft)) * 100)}%`
                      : undefined
                  }
                />
                <ValuePair
                  label="Headcount Capacity"
                  value={office.headcount_capacity ?? undefined}
                />
                <ValuePair
                  label="Current Headcount"
                  value={office.current_headcount ?? undefined}
                />
                <ValuePair
                  label="Occupancy Rate"
                  value={
                    office.headcount_capacity && office.current_headcount
                      ? `${Math.round((office.current_headcount / office.headcount_capacity) * 100)}%`
                      : undefined
                  }
                />
                <ValuePair
                  label="Space Type"
                  value={
                    office.space_type
                      ? office.space_type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
                      : undefined
                  }
                />
              </ColumnLayout>
            </Container>
          )}

          {/* ── Related Data Tabs ──────────────────────────────────────────────── */}
          <Tabs
            tabs={[
              {
                id: 'leases',
                label: `Leases (${leases.length})`,
                content: (
                  <Table
                    loading={leasesLoading}
                    loadingText="Loading leases..."
                    columnDefinitions={[
                      {
                        id: 'lease_name',
                        header: 'Lease Name',
                        cell: (item: Lease) => (
                          <Link onFollow={() => navigate(`/leases/${item.id}`)}>
                            {item.lease_name}
                          </Link>
                        ),
                      },
                      {
                        id: 'lessor_name',
                        header: 'Lessor',
                        cell: (item: Lease) =>
                          item.lessor_name || item.landlord?.name || '—',
                      },
                      {
                        id: 'lease_expiration',
                        header: 'Expiration',
                        cell: (item: Lease) =>
                          item.lease_expiration
                            ? new Date(item.lease_expiration).toLocaleDateString()
                            : '—',
                      },
                      {
                        id: 'monthly_rent',
                        header: 'Monthly Rent',
                        cell: (item: Lease) =>
                          item.monthly_rent != null
                            ? `$${item.monthly_rent.toLocaleString()}`
                            : '—',
                      },
                      {
                        id: 'notice_given',
                        header: 'Notice Given',
                        cell: (item: Lease) => (
                          <StatusIndicator type={item.notice_given ? 'success' : 'pending'}>
                            {item.notice_given ? 'Yes' : 'No'}
                          </StatusIndicator>
                        ),
                      },
                    ]}
                    items={leases}
                    header={
                      <Header
                        counter={`(${leases.length})`}
                        actions={
                          <Button onClick={() => navigate(`/leases/new?office_id=${id}`)}>
                            Add Lease
                          </Button>
                        }
                      >
                        Leases
                      </Header>
                    }
                    empty={
                      <Box textAlign="center" color="inherit" padding="l">
                        <SpaceBetween size="m">
                          <b>No leases for this office</b>
                          <Button onClick={() => navigate(`/leases/new?office_id=${id}`)}>
                            Add lease
                          </Button>
                        </SpaceBetween>
                      </Box>
                    }
                    variant="embedded"
                  />
                ),
              },
              {
                id: 'landlord',
                label: `Landlord${officeLandlords.length ? ` (${officeLandlords.length})` : ''}`,
                content: (
                  <Box padding={{ top: 'm' }}>
                    {officeLandlords.length > 0 ? (
                      <SpaceBetween size="l">
                        {officeLandlords.map((ll) => (
                          <Container
                            key={ll.id}
                            header={
                              <Header
                                variant="h3"
                                actions={
                                  <Button onClick={() => navigate(`/landlords/${ll.id}`)}>
                                    View full record
                                  </Button>
                                }
                              >
                                {ll.landlord_company || ll.contact_name || 'Landlord'}
                              </Header>
                            }
                          >
                            <SpaceBetween size="m">
                              <ColumnLayout columns={3} variant="text-grid">
                                <ValuePair label="Contact Name" value={ll.contact_name} />
                                <ValuePair label="Company" value={ll.landlord_company} />
                                <ValuePair label="Management Company" value={ll.management_company} />
                                <ValuePair label="Entity Type" value={ll.entity_type} />
                                <ValuePair label="Email" value={ll.contact_email} />
                                <ValuePair label="Phone" value={ll.contact_phone} />
                                <ValuePair label="Secondary Phone" value={ll.secondary_phone} />
                                <ValuePair label="Fax" value={ll.fax} />
                                <ValuePair
                                  label="Website"
                                  value={
                                    ll.website ? (
                                      <Link external href={ll.website}>
                                        {ll.website}
                                      </Link>
                                    ) : undefined
                                  }
                                />
                                <ValuePair
                                  label="Preferred Payment"
                                  value={ll.preferred_payment_method}
                                />
                                <ValuePair label="Payment Terms" value={ll.payment_terms} />
                                <ValuePair
                                  label="Property Address"
                                  value={
                                    <span style={{ whiteSpace: 'pre-line' }}>
                                      {formatAddress(
                                        {
                                          address_line_1: ll.address_line_1,
                                          address_line_2: ll.address_line_2,
                                          city: ll.city,
                                          state: ll.state,
                                          zip_code: ll.zip_code,
                                        },
                                        ll.address,
                                      ) || '—'}
                                    </span>
                                  }
                                />
                                <ValuePair
                                  label="Mailing Address"
                                  value={
                                    <span style={{ whiteSpace: 'pre-line' }}>
                                      {formatAddress(
                                        {
                                          address_line_1: ll.mailing_address_line_1,
                                          address_line_2: ll.mailing_address_line_2,
                                          city: ll.mailing_city,
                                          state: ll.mailing_state,
                                          zip_code: ll.mailing_zip_code,
                                        },
                                        ll.contact_mailing_address,
                                      ) || '—'}
                                    </span>
                                  }
                                />
                              </ColumnLayout>
                              {(ll.contacts ?? []).length > 0 && (
                                <Table<LandlordContact>
                                  variant="embedded"
                                  header={
                                    <Header variant="h3" counter={`(${(ll.contacts ?? []).length})`}>
                                      Additional Contacts
                                    </Header>
                                  }
                                  columnDefinitions={[
                                    { id: 'name', header: 'Name', cell: (c) => c.contact_name },
                                    {
                                      id: 'type',
                                      header: 'Type',
                                      cell: (c) =>
                                        c.contact_type
                                          ? c.contact_type
                                              .replace(/_/g, ' ')
                                              .replace(/\b\w/g, (ch) => ch.toUpperCase())
                                          : '—',
                                    },
                                    {
                                      id: 'primary',
                                      header: 'Primary',
                                      cell: (c) =>
                                        c.is_primary ? (
                                          <StatusIndicator type="success">Primary</StatusIndicator>
                                        ) : (
                                          '—'
                                        ),
                                    },
                                    { id: 'email', header: 'Email', cell: (c) => c.email || '—' },
                                    { id: 'phone', header: 'Phone', cell: (c) => c.phone || '—' },
                                  ]}
                                  items={ll.contacts ?? []}
                                />
                              )}
                            </SpaceBetween>
                          </Container>
                        ))}
                      </SpaceBetween>
                    ) : primaryLandlord ? (
                      <Container>
                        <SpaceBetween size="m">
                          <ColumnLayout columns={2} variant="text-grid">
                            <ValuePair label="Name" value={primaryLandlord.contact_name} />
                            <ValuePair label="Company" value={primaryLandlord.landlord_company} />
                            <ValuePair label="Email" value={primaryLandlord.contact_email} />
                            <ValuePair label="Phone" value={primaryLandlord.contact_phone} />
                            <ValuePair
                              label="Property Address"
                              value={
                                <span style={{ whiteSpace: 'pre-line' }}>
                                  {formatAddress(
                                    {
                                      address_line_1: primaryLandlord.address_line_1,
                                      address_line_2: primaryLandlord.address_line_2,
                                      city: primaryLandlord.city,
                                      state: primaryLandlord.state,
                                      zip_code: primaryLandlord.zip_code,
                                    },
                                    primaryLandlord.address,
                                  ) || '—'}
                                </span>
                              }
                            />
                            <ValuePair
                              label="Mailing Address"
                              value={
                                <span style={{ whiteSpace: 'pre-line' }}>
                                  {formatAddress(
                                    {
                                      address_line_1: primaryLandlord.mailing_address_line_1,
                                      address_line_2: primaryLandlord.mailing_address_line_2,
                                      city: primaryLandlord.mailing_city,
                                      state: primaryLandlord.mailing_state,
                                      zip_code: primaryLandlord.mailing_zip_code,
                                    },
                                    primaryLandlord.contact_mailing_address,
                                  ) || '—'}
                                </span>
                              }
                            />
                          </ColumnLayout>
                          <Link onFollow={() => navigate(`/landlords/${primaryLandlord.id}`)}>
                            View full landlord record
                          </Link>
                        </SpaceBetween>
                      </Container>
                    ) : landlordsLoading ? (
                      <Box textAlign="center" color="text-body-secondary" padding="l">
                        Loading landlord information…
                      </Box>
                    ) : (
                      <Box textAlign="center" color="text-body-secondary" padding="l">
                        No landlord information available for this office.{' '}
                        <Link onFollow={() => navigate('/landlords')}>View all landlords</Link>
                      </Box>
                    )}
                  </Box>
                ),
              },
              {
                id: 'hvac',
                label: `HVAC (${hvacContracts.length})`,
                content: (
                  <Table
                    loading={hvacLoading}
                    loadingText="Loading HVAC contracts..."
                    columnDefinitions={[
                      {
                        id: 'vendor_name',
                        header: 'Vendor',
                        cell: (item: HvacContract) => (
                          <Link onFollow={() => navigate(`/hvac-contracts/${item.id}`)}>
                            {item.vendor_name}
                          </Link>
                        ),
                      },
                      {
                        id: 'frequency',
                        header: 'Frequency',
                        cell: (item: HvacContract) => item.frequency,
                      },
                      {
                        id: 'next_service_date',
                        header: 'Next Service',
                        cell: (item: HvacContract) =>
                          item.next_service_date
                            ? new Date(item.next_service_date).toLocaleDateString()
                            : '—',
                      },
                      {
                        id: 'landlord_managed',
                        header: 'Landlord Managed',
                        cell: (item: HvacContract) => (
                          <StatusIndicator type={item.landlord_managed ? 'success' : 'info'}>
                            {item.landlord_managed ? 'Yes' : 'No'}
                          </StatusIndicator>
                        ),
                      },
                      {
                        id: 'annual_cost',
                        header: 'Annual Cost',
                        cell: (item: HvacContract) =>
                          item.annual_cost != null
                            ? `$${item.annual_cost.toLocaleString()}`
                            : '—',
                      },
                    ]}
                    items={hvacContracts}
                    header={
                      <Header counter={`(${hvacContracts.length})`}>HVAC Contracts</Header>
                    }
                    empty={
                      <Box textAlign="center" color="text-body-secondary" padding="l">
                        No HVAC contracts for this office.{' '}
                        <Link onFollow={() => navigate('/hvac-contracts')}>
                          View all HVAC contracts
                        </Link>
                      </Box>
                    }
                    variant="embedded"
                  />
                ),
              },
              {
                id: 'tickets',
                label: `Tickets (${tickets.length})`,
                content: (
                  <Table
                    loading={ticketsLoading}
                    loadingText="Loading tickets..."
                    columnDefinitions={[
                      {
                        id: 'subject',
                        header: 'Subject',
                        cell: (item: MaintenanceTicket) => (
                          <Link onFollow={() => navigate(`/maintenance-tickets/${item.id}`)}>
                            {item.subject}
                          </Link>
                        ),
                      },
                      {
                        id: 'priority',
                        header: 'Priority',
                        cell: (item: MaintenanceTicket) => (
                          <Badge color={item.priority === 'high' ? 'red' : item.priority === 'medium' ? 'blue' : 'grey'}>
                            {item.priority.charAt(0).toUpperCase() + item.priority.slice(1)}
                          </Badge>
                        ),
                      },
                      {
                        id: 'status',
                        header: 'Status',
                        cell: (item: MaintenanceTicket) => (
                          <StatusIndicator
                            type={item.status === 'closed' ? 'success' : item.status === 'in_progress' ? 'in-progress' : 'pending'}
                          >
                            {item.status.charAt(0).toUpperCase() + item.status.slice(1).replace(/_/g, ' ')}
                          </StatusIndicator>
                        ),
                      },
                      {
                        id: 'created_at',
                        header: 'Created',
                        cell: (item: MaintenanceTicket) =>
                          item.created_at ? new Date(item.created_at).toLocaleDateString() : '—',
                      },
                    ]}
                    items={tickets}
                    header={<Header counter={`(${tickets.length})`}>Maintenance Tickets</Header>}
                    empty={
                      <Box textAlign="center" color="inherit" padding="l">
                        No maintenance tickets for this office.
                      </Box>
                    }
                    variant="embedded"
                  />
                ),
              },
              {
                id: 'transitions',
                label: `Transitions (${officeTransitions.length})`,
                content: (
                  <Table
                    loading={transitionsLoading}
                    loadingText="Loading transitions..."
                    columnDefinitions={[
                      {
                        id: 'sheet_name',
                        header: 'Name',
                        cell: (item: Transition) => (
                          <Link onFollow={() => navigate(`/transitions/${item.id}`)}>
                            {item.sheet_name || `Office #${item.office_number}`}
                          </Link>
                        ),
                      },
                      {
                        id: 'type',
                        header: 'Type',
                        cell: (item: Transition) =>
                          item.transition_type.charAt(0).toUpperCase() + item.transition_type.slice(1),
                      },
                      {
                        id: 'status',
                        header: 'Status',
                        cell: (item: Transition) => (
                          <StatusIndicator
                            type={
                              item.status === 'completed' ? 'success'
                                : item.status === 'in_progress' ? 'in-progress'
                                : item.status === 'cancelled' ? 'error'
                                : 'pending'
                            }
                          >
                            {item.status.charAt(0).toUpperCase() + item.status.slice(1).replace(/_/g, ' ')}
                          </StatusIndicator>
                        ),
                      },
                      {
                        id: 'target_date',
                        header: 'Target Date',
                        cell: (item: Transition) => item.target_date ?? '—',
                      },
                    ]}
                    items={officeTransitions}
                    header={<Header counter={`(${officeTransitions.length})`}>Transitions</Header>}
                    empty={
                      <Box textAlign="center" color="inherit" padding="l">
                        No transitions for this office.
                      </Box>
                    }
                    variant="embedded"
                  />
                ),
              },
              {
                id: 'space_history',
                label: `Space History (${spaceHistory.length})`,
                content: (
                  <SpaceBetween size="m">
                    <Table
                      loading={spaceHistoryLoading}
                      loadingText="Loading space history..."
                      columnDefinitions={[
                        {
                          id: 'date',
                          header: 'Snapshot Date',
                          cell: (s: SpaceSnapshot) =>
                            new Date(s.snapshot_date).toLocaleDateString(),
                        },
                        {
                          id: 'headcount',
                          header: 'Headcount',
                          cell: (s: SpaceSnapshot) =>
                            s.current_headcount != null
                              ? `${s.current_headcount} / ${s.headcount_capacity ?? '?'}`
                              : '—',
                        },
                        {
                          id: 'occupancy',
                          header: 'Occupancy',
                          cell: (s: SpaceSnapshot) =>
                            s.occupancy_pct != null ? `${s.occupancy_pct}%` : '—',
                        },
                        {
                          id: 'total_sqft',
                          header: 'Total Sqft',
                          cell: (s: SpaceSnapshot) =>
                            s.total_sqft != null
                              ? `${Number(s.total_sqft).toLocaleString()} sqft`
                              : '—',
                        },
                        {
                          id: 'usable_sqft',
                          header: 'Usable Sqft',
                          cell: (s: SpaceSnapshot) =>
                            s.usable_sqft != null
                              ? `${Number(s.usable_sqft).toLocaleString()} sqft`
                              : '—',
                        },
                        {
                          id: 'spp',
                          header: 'Sqft / Person',
                          cell: (s: SpaceSnapshot) =>
                            s.sqft_per_person != null ? `${s.sqft_per_person}` : '—',
                        },
                        {
                          id: 'notes',
                          header: 'Notes',
                          cell: (s: SpaceSnapshot) => s.notes ?? '—',
                        },
                        ...(user?.role === 'admin' ? [{
                          id: 'actions',
                          header: '',
                          cell: (s: SpaceSnapshot) => (
                            <Button
                              variant="inline-link"
                              loading={deletingSnapshotId === s.id}
                              onClick={() => handleDeleteSnapshot(s.id)}
                            >
                              Delete
                            </Button>
                          ),
                          width: 80,
                        }] : []),
                      ]}
                      items={spaceHistory}
                      header={
                        <Header
                          counter={`(${spaceHistory.length})`}
                          actions={
                            (user?.role === 'admin' || user?.role === 'editor') && (
                              <Button
                                onClick={() => {
                                  setSnapshotForm({
                                    current_headcount: String(office?.current_headcount ?? ''),
                                    notes: '',
                                    snapshot_date: new Date().toISOString().slice(0, 16),
                                  });
                                  setShowSnapshotModal(true);
                                }}
                              >
                                Record Snapshot
                              </Button>
                            )
                          }
                        >
                          Space History
                        </Header>
                      }
                      empty={
                        <Box textAlign="center" color="inherit" padding="l">
                          No snapshots recorded yet.{' '}
                          {(user?.role === 'admin' || user?.role === 'editor') && (
                            <Link
                              onFollow={() => {
                                setSnapshotForm({
                                  current_headcount: String(office?.current_headcount ?? ''),
                                  notes: '',
                                  snapshot_date: new Date().toISOString().slice(0, 16),
                                });
                                setShowSnapshotModal(true);
                              }}
                            >
                              Record the first snapshot
                            </Link>
                          )}
                        </Box>
                      }
                      variant="embedded"
                    />
                    {spaceHistory.length >= 2 && (
                      <BarChart
                        series={[{
                          title: 'Occupancy %',
                          type: 'bar',
                          data: spaceHistory
                            .filter(s => s.occupancy_pct != null)
                            .map(s => ({
                              x: new Date(s.snapshot_date).toLocaleDateString(),
                              y: s.occupancy_pct!,
                            })),
                          valueFormatter: v => `${v}%`,
                        }]}
                        xDomain={spaceHistory
                          .filter(s => s.occupancy_pct != null)
                          .map(s => new Date(s.snapshot_date).toLocaleDateString())}
                        yTitle="Occupancy %"
                        xTitle="Snapshot Date"
                        height={220}
                        empty={<Box textAlign="center">No occupancy data</Box>}
                      />
                    )}
                  </SpaceBetween>
                ),
              },
            ]}
          />

          {/* Attachments */}
          {id && (
            <AttachmentsPanel
              entityType="office"
              entityId={id}
              canEdit={user?.role === 'admin' || user?.role === 'editor'}
            />
          )}

          {/* Activity Log */}
          {id && <ActivityTimeline entityType="office" entityId={id} />}
        </SpaceBetween>
      </ContentLayout>

      {/* Record Snapshot Modal */}
      <Modal
        visible={showSnapshotModal}
        onDismiss={() => setShowSnapshotModal(false)}
        header="Record Space Snapshot"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowSnapshotModal(false)}>Cancel</Button>
              <Button variant="primary" loading={savingSnapshot} onClick={handleSaveSnapshot}>
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
          <FormField label="Current Headcount" constraintText="Leave blank to use the office's current headcount">
            <Input
              type="number"
              value={snapshotForm.current_headcount}
              onChange={({ detail }) =>
                setSnapshotForm(prev => ({ ...prev, current_headcount: detail.value }))
              }
              placeholder={String(office?.current_headcount ?? '')}
            />
          </FormField>
          <FormField label="Notes" constraintText="Optional">
            <Input
              value={snapshotForm.notes}
              onChange={({ detail }) =>
                setSnapshotForm(prev => ({ ...prev, notes: detail.value }))
              }
              placeholder="Any notes about this snapshot"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
};

export default OfficeDetailPage;
