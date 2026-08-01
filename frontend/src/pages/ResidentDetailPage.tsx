import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Button from '@cloudscape-design/components/button';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Link from '@cloudscape-design/components/link';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';
import { useAuth } from '@/auth/AuthContext';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import PortalInviteButton from '@/components/common/PortalInviteButton';
import { leasing, rent as rentApi } from '@/api';
import type {
  RentCharge,
  RentalUnit,
  Resident,
  ResidentLease,
  ResidentStatus,
  SecurityDeposit,
} from '@/types';

const money = (v: string | null | undefined) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const date = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleDateString() : '—';

const statusBadge = (s: ResidentStatus) => {
  const color = s === 'current' ? 'green' : s === 'prospect' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value || '—'}</Box>
  </div>
);

/**
 * Resident master record — the single place that answers "who is this resident,
 * where do they live, what do they owe, and what have we signed with them".
 * Previously this data was split across the Residents, Leases, and Rent tabs.
 */
const ResidentDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [resident, setResident] = useState<Resident | null>(null);
  const [leases, setLeases] = useState<ResidentLease[]>([]);
  const [units, setUnits] = useState<RentalUnit[]>([]);
  const [charges, setCharges] = useState<RentCharge[]>([]);
  const [deposits, setDeposits] = useState<SecurityDeposit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [res, leaseRes] = await Promise.all([
        leasing.getResident(id),
        leasing.listLeases({ resident_id: id }),
      ]);
      setResident(res.data);
      setLeases(leaseRes.data);

      const leaseIds = leaseRes.data.map((l) => l.id);

      // Resolve only the units this resident actually occupies.
      const unitIds = Array.from(new Set(leaseRes.data.map((l) => l.unit_id)));
      Promise.all(
        unitIds.map((unitId) =>
          leasing
            .getUnit(unitId)
            .then((r) => r.data)
            .catch(() => null),
        ),
      ).then((loaded) => setUnits(loaded.filter((u): u is RentalUnit => u !== null)));

      // Rent charges and deposits are per-lease and finance-gated, so they are
      // fetched best-effort and simply omitted when the caller lacks access.
      const [chargeLists, depositLists] = await Promise.all([
        Promise.all(
          leaseIds.map((leaseId) =>
            rentApi
              .listCharges({ resident_lease_id: leaseId })
              .then((r) => r.data)
              .catch(() => [] as RentCharge[]),
          ),
        ),
        Promise.all(
          leaseIds.map((leaseId) =>
            rentApi
              .listDeposits({ resident_lease_id: leaseId })
              .then((r) => r.data)
              .catch(() => [] as SecurityDeposit[]),
          ),
        ),
      ]);
      setCharges(chargeLists.flat());
      setDeposits(depositLists.flat());
    } catch {
      setError('Failed to load resident.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const unitLabel = useCallback(
    (unitId: string) => {
      const u = units.find((x) => x.id === unitId);
      if (!u) return unitId;
      return u.name || `Unit ${u.unit_number}`;
    },
    [units],
  );

  const activeLease = useMemo(
    () => leases.find((l) => l.status === 'active') ?? null,
    [leases],
  );

  const monthlyRecurring = useMemo(
    () =>
      charges
        .filter((c) => c.active)
        .reduce((sum, c) => sum + Number(c.amount || 0), 0),
    [charges],
  );

  const depositsHeld = useMemo(
    () =>
      deposits
        .filter((d) => d.status !== 'returned')
        .reduce((sum, d) => sum + Number(d.amount || 0), 0),
    [deposits],
  );

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error || !resident) {
    return <Alert type="error">{error || 'Resident not found.'}</Alert>;
  }

  const fullName = `${resident.first_name} ${resident.last_name}`.trim();

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Residential', href: '/residential' },
              { text: 'Residents', href: '/residential/residents' },
              { text: fullName, href: `/residential/residents/${id}` },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Everything on record for this resident: tenancy, money, and documents."
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <PortalInviteButton
                  entityLabel="resident"
                  entityName={fullName}
                  onInvite={() => leasing.inviteToPortal(resident.id)}
                />
                {canEdit && (
                  <Button
                    onClick={() =>
                      navigate(`/residential/residents?edit=${resident.id}`)
                    }
                  >
                    Edit
                  </Button>
                )}
              </SpaceBetween>
            }
          >
            {fullName}
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">At a glance</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            <ValuePair label="Status" value={statusBadge(resident.status)} />
            <ValuePair
              label="Current unit"
              value={
                activeLease ? (
                  <Link
                    onFollow={(e) => {
                      e.preventDefault();
                      navigate(`/residential/units/${activeLease.unit_id}`);
                    }}
                    href={`/residential/units/${activeLease.unit_id}`}
                  >
                    {unitLabel(activeLease.unit_id)}
                  </Link>
                ) : (
                  'No active lease'
                )
              }
            />
            <ValuePair
              label="Recurring monthly charges"
              value={charges.length ? money(String(monthlyRecurring)) : '—'}
            />
            <ValuePair
              label="Deposits held"
              value={deposits.length ? money(String(depositsHeld)) : '—'}
            />
          </ColumnLayout>
        </Container>

        <Container header={<Header variant="h2">Contact</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <ValuePair label="Email" value={resident.email} />
            <ValuePair label="Phone" value={resident.phone} />
            <ValuePair label="Alternate phone" value={resident.alternate_phone} />
            <ValuePair label="Company" value={resident.company} />
            <ValuePair
              label="Emergency contact"
              value={
                resident.emergency_contact_name
                  ? `${resident.emergency_contact_name}${
                      resident.emergency_contact_phone
                        ? ` · ${resident.emergency_contact_phone}`
                        : ''
                    }`
                  : null
              }
            />
            <ValuePair
              label="Mailing address"
              value={
                [
                  resident.address_line_1,
                  resident.address_line_2,
                  [resident.city, resident.state, resident.zip_code]
                    .filter(Boolean)
                    .join(' '),
                ]
                  .filter(Boolean)
                  .join(', ') || null
              }
            />
          </ColumnLayout>
        </Container>

        <Table<ResidentLease>
          variant="container"
          items={leases}
          header={
            <Header
              variant="h2"
              counter={`(${leases.length})`}
              actions={
                <Button onClick={() => navigate('/residential/leases')}>
                  All resident leases
                </Button>
              }
            >
              Leases
            </Header>
          }
          columnDefinitions={[
            {
              id: 'unit',
              header: 'Unit',
              cell: (l) => (
                <Link
                  onFollow={(e) => {
                    e.preventDefault();
                    navigate(`/residential/units/${l.unit_id}`);
                  }}
                  href={`/residential/units/${l.unit_id}`}
                >
                  {unitLabel(l.unit_id)}
                </Link>
              ),
            },
            { id: 'status', header: 'Status', cell: (l) => <Badge>{l.status}</Badge> },
            {
              id: 'term',
              header: 'Term',
              cell: (l) => `${date(l.start_date)} – ${date(l.end_date)}`,
            },
            { id: 'rent', header: 'Rent', cell: (l) => money(l.rent_amount) },
            { id: 'deposit', header: 'Security deposit', cell: (l) => money(l.security_deposit) },
          ]}
          empty={
            <Box textAlign="center" padding="m">
              <SpaceBetween size="xs">
                <Box>No leases recorded for this resident.</Box>
                <Button onClick={() => navigate('/residential/leases')}>
                  Add a lease
                </Button>
              </SpaceBetween>
            </Box>
          }
        />

        {charges.length > 0 && (
          <Table<RentCharge>
            variant="container"
            items={charges}
            header={
              <Header variant="h2" counter={`(${charges.length})`}>
                Recurring charges
              </Header>
            }
            columnDefinitions={[
              { id: 'type', header: 'Type', cell: (c) => c.charge_type },
              { id: 'description', header: 'Description', cell: (c) => c.description || '—' },
              { id: 'amount', header: 'Amount', cell: (c) => money(c.amount) },
              { id: 'frequency', header: 'Frequency', cell: (c) => c.frequency },
              {
                id: 'active',
                header: 'Active',
                cell: (c) => (c.active ? 'Yes' : 'No'),
              },
            ]}
          />
        )}

        {deposits.length > 0 && (
          <Table<SecurityDeposit>
            variant="container"
            items={deposits}
            header={
              <Header variant="h2" counter={`(${deposits.length})`}>
                Security deposits
              </Header>
            }
            columnDefinitions={[
              { id: 'amount', header: 'Amount', cell: (d) => money(d.amount) },
              { id: 'held', header: 'Held since', cell: (d) => date(d.held_date) },
              { id: 'status', header: 'Status', cell: (d) => <Badge>{d.status}</Badge> },
              { id: 'returned', header: 'Returned', cell: (d) => money(d.returned_amount) },
            ]}
          />
        )}

        {resident.notes && (
          <Container header={<Header variant="h2">Notes</Header>}>
            <Box>
              <span style={{ whiteSpace: 'pre-wrap' }}>{resident.notes}</span>
            </Box>
          </Container>
        )}

        <AttachmentsPanel
          entityType="resident"
          entityId={resident.id}
          canEdit={canEdit}
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default ResidentDetailPage;
