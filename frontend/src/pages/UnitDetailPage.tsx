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
import { leasing, listings as listingsApi, offices as officesApi } from '@/api';
import type {
  Occupant,
  Office,
  RentalUnit,
  ResidentLease,
  UnitStatus,
  VacancyListing,
} from '@/types';

const money = (v: string | null | undefined) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const date = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleDateString() : '—';

const unitBadge = (s: UnitStatus) => {
  const color = s === 'available' ? 'green' : s === 'occupied' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value || '—'}</Box>
  </div>
);

/**
 * Rental unit master record — occupancy, tenancy history, marketing status and
 * documents for one unit, instead of spreading them across the Units, Leases
 * and Listings tabs.
 */
const UnitDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [unit, setUnit] = useState<RentalUnit | null>(null);
  const [leases, setLeases] = useState<ResidentLease[]>([]);
  const [unitListings, setUnitListings] = useState<VacancyListing[]>([]);
  const [office, setOffice] = useState<Office | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [unitRes, leaseRes] = await Promise.all([
        leasing.getUnit(id),
        leasing.listLeases({ unit_id: id }),
      ]);
      setUnit(unitRes.data);
      setLeases(leaseRes.data);

      if (unitRes.data.office_id) {
        officesApi
          .get(unitRes.data.office_id)
          .then((r) => setOffice(r.data))
          .catch(() => undefined);
      }
      listingsApi
        .list({ unit_id: id })
        .then((r) => setUnitListings(r.data))
        .catch(() => undefined);
    } catch {
      setError('Failed to load unit.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const activeLease = useMemo(
    () => leases.find((l) => l.status === 'active') ?? null,
    [leases],
  );

  const currentOccupants: Occupant[] = activeLease?.occupants ?? [];

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error || !unit) {
    return <Alert type="error">{error || 'Unit not found.'}</Alert>;
  }

  const title = unit.name || `Unit ${unit.unit_number}`;

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Residential', href: '/residential' },
              { text: 'Units', href: '/residential' },
              { text: title, href: `/residential/units/${id}` },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            description="Occupancy, tenancy history, marketing status and documents for this unit."
            actions={
              canEdit && (
                <Button onClick={() => navigate(`/residential?edit=${unit.id}`)}>
                  Edit
                </Button>
              )
            }
          >
            {title}
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">At a glance</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            <ValuePair label="Status" value={unitBadge(unit.status)} />
            <ValuePair
              label="Occupied by"
              value={
                currentOccupants.length ? (
                  <SpaceBetween size="xxs">
                    {currentOccupants.map((o) =>
                      o.resident ? (
                        <Link
                          key={o.id}
                          onFollow={(e) => {
                            e.preventDefault();
                            navigate(`/residential/residents/${o.resident_id}`);
                          }}
                          href={`/residential/residents/${o.resident_id}`}
                        >
                          {`${o.resident.first_name} ${o.resident.last_name}`.trim()}
                        </Link>
                      ) : (
                        <Box key={o.id}>Resident {o.resident_id}</Box>
                      ),
                    )}
                  </SpaceBetween>
                ) : (
                  'Vacant'
                )
              }
            />
            <ValuePair label="Market rent" value={money(unit.market_rent)} />
            <ValuePair
              label="Current rent"
              value={activeLease ? money(activeLease.rent_amount) : '—'}
            />
          </ColumnLayout>
        </Container>

        <Container header={<Header variant="h2">Unit details</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            <ValuePair label="Unit number" value={unit.unit_number} />
            <ValuePair
              label="Property"
              value={
                office ? (
                  <Link
                    onFollow={(e) => {
                      e.preventDefault();
                      navigate(`/offices/${office.id}`);
                    }}
                    href={`/offices/${office.id}`}
                  >
                    {`${office.office_number} · ${office.location_name}`}
                  </Link>
                ) : null
              }
            />
            <ValuePair label="Floor" value={unit.floor} />
            <ValuePair label="Property type" value={unit.property_type} />
            <ValuePair label="Bedrooms" value={unit.bedrooms?.toString()} />
            <ValuePair label="Bathrooms" value={unit.bathrooms} />
            <ValuePair label="Square feet" value={unit.square_feet} />
            <ValuePair label="Year built" value={unit.year_built?.toString()} />
            <ValuePair label="Available date" value={date(unit.available_date)} />
            <ValuePair
              label="Address"
              value={
                [
                  unit.address_line_1,
                  unit.address_line_2,
                  [unit.city, unit.state, unit.zip_code].filter(Boolean).join(' '),
                ]
                  .filter(Boolean)
                  .join(', ') || null
              }
            />
            <ValuePair label="Amenities" value={unit.amenities} />
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
              Tenancy history
            </Header>
          }
          columnDefinitions={[
            {
              id: 'occupants',
              header: 'Occupants',
              cell: (l) =>
                l.occupants.length
                  ? l.occupants
                      .map((o) =>
                        o.resident
                          ? `${o.resident.first_name} ${o.resident.last_name}`.trim()
                          : 'Unknown',
                      )
                      .join(', ')
                  : '—',
            },
            { id: 'status', header: 'Status', cell: (l) => <Badge>{l.status}</Badge> },
            {
              id: 'term',
              header: 'Term',
              cell: (l) => `${date(l.start_date)} – ${date(l.end_date)}`,
            },
            { id: 'rent', header: 'Rent', cell: (l) => money(l.rent_amount) },
            { id: 'movein', header: 'Move in', cell: (l) => date(l.move_in_date) },
            { id: 'moveout', header: 'Move out', cell: (l) => date(l.move_out_date) },
          ]}
          empty={<Box textAlign="center" padding="m">No tenancy recorded for this unit.</Box>}
        />

        <Table<VacancyListing>
          variant="container"
          items={unitListings}
          header={
            <Header
              variant="h2"
              counter={`(${unitListings.length})`}
              actions={
                <Button onClick={() => navigate('/residential/listings')}>
                  All listings
                </Button>
              }
            >
              Marketing listings
            </Header>
          }
          columnDefinitions={[
            { id: 'title', header: 'Title', cell: (l) => l.title || '—' },
            { id: 'status', header: 'Status', cell: (l) => <Badge>{l.status}</Badge> },
            { id: 'rent', header: 'Asking rent', cell: (l) => money(l.marketing_rent) },
            { id: 'available', header: 'Available', cell: (l) => date(l.available_date) },
          ]}
          empty={
            <Box textAlign="center" padding="m">
              No listings for this unit.
            </Box>
          }
        />

        {unit.notes && (
          <Container header={<Header variant="h2">Notes</Header>}>
            <Box>
              <span style={{ whiteSpace: 'pre-wrap' }}>{unit.notes}</span>
            </Box>
          </Container>
        )}

        <AttachmentsPanel entityType="rental_unit" entityId={unit.id} canEdit={canEdit} />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default UnitDetailPage;
