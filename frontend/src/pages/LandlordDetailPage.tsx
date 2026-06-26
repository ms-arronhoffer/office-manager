import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Table from '@cloudscape-design/components/table';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Link from '@cloudscape-design/components/link';
import { landlords as landlordsApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import ContactsPanel from '@/components/common/ContactsPanel';
import ClientPortalInvitePanel from '@/components/common/ClientPortalInvitePanel';
import { formatAddress } from '@/components/common/AddressFields';
import type { Landlord, LandlordAdditionalName, LandlordOfficeRef } from '@/types';

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value || '—'}</Box>
  </div>
);

const LandlordDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();

  const [landlord, setLandlord] = useState<Landlord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchLandlord = useCallback(async () => {
    if (!id) return;
    try {
      const res = await landlordsApi.get(id);
      setLandlord(res.data);
    } catch {
      setError('Failed to load landlord details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchLandlord();
  }, [fetchLandlord]);

  const handleDelete = async () => {
    if (!id || !landlord) return;
    try {
      await landlordsApi.delete(id);
      const label = landlord.landlord_company || landlord.contact_name || landlord.office_name || 'Landlord';
      navigate('/landlords');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button variant="link" onClick={async () => {
              try {
                await landlordsApi.restore(id);
                navigate(`/landlords/${id}`);
              } catch {
                addFlash({ type: 'error', content: 'Failed to undo delete.' });
              }
            }}>Undo</Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete landlord.');
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error || !landlord) {
    return <Alert type="error">{error || 'Landlord not found.'}</Alert>;
  }

  return (
    <>
      {deleteModal}
      <ContentLayout
        header={
          <SpaceBetween size="m">
            <BreadcrumbGroup
              items={[
                { text: 'Home', href: '/' },
                { text: 'Landlords', href: '/landlords' },
                { text: landlord.contact_name || landlord.landlord_company || 'Landlord', href: `/landlords/${id}` },
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
                  <Button onClick={() => navigate(`/landlords/${id}/edit`)}>Edit</Button>
                  <Button variant="normal" onClick={() => confirmDelete({
                    itemName: landlord.landlord_company || landlord.contact_name || landlord.office_name || 'Landlord',
                    onConfirm: handleDelete,
                  })}>
                    Delete
                  </Button>
                </SpaceBetween>
              }
            >
              {landlord.landlord_company || landlord.contact_name || landlord.office_name || 'Landlord'}
            </Header>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Landlord Information</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <ValuePair label="Name" value={landlord.contact_name} />
              <ValuePair label="Company" value={landlord.landlord_company} />
              <ValuePair label="Entity Type" value={landlord.entity_type} />
              <ValuePair label="Tax ID / EIN" value={landlord.tax_id} />
              <ValuePair label="Email" value={landlord.contact_email} />
              <ValuePair label="Phone" value={landlord.contact_phone} />
              <ValuePair label="Secondary Phone" value={landlord.secondary_phone} />
              <ValuePair label="Fax" value={landlord.fax} />
              <ValuePair
                label="Website"
                value={
                  landlord.website ? (
                    <Link external href={landlord.website}>
                      {landlord.website}
                    </Link>
                  ) : undefined
                }
              />
              <ValuePair label="Preferred Payment Method" value={landlord.preferred_payment_method} />
              <ValuePair label="Payment Terms" value={landlord.payment_terms} />
              <ValuePair
                label="Property Address"
                value={
                  <span style={{ whiteSpace: 'pre-line' }}>
                    {formatAddress(
                      {
                        address_line_1: landlord.address_line_1,
                        address_line_2: landlord.address_line_2,
                        city: landlord.city,
                        state: landlord.state,
                        zip_code: landlord.zip_code,
                      },
                      landlord.address,
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
                        address_line_1: landlord.mailing_address_line_1,
                        address_line_2: landlord.mailing_address_line_2,
                        city: landlord.mailing_city,
                        state: landlord.mailing_state,
                        zip_code: landlord.mailing_zip_code,
                      },
                      landlord.contact_mailing_address,
                    ) || '—'}
                  </span>
                }
              />
            </ColumnLayout>
          </Container>

          {/* Property Management Company */}
          {(landlord.management_company_ref || landlord.management_company) && (
            <Container header={<Header variant="h2">Property Management Company</Header>}>
              {landlord.management_company_ref ? (
                <ColumnLayout columns={3} variant="text-grid">
                  <ValuePair
                    label="Company"
                    value={
                      <Link
                        onFollow={() =>
                          navigate(`/management-companies/${landlord.management_company_ref!.id}`)
                        }
                      >
                        {landlord.management_company_ref.name}
                      </Link>
                    }
                  />
                  <ValuePair
                    label="Contact"
                    value={landlord.management_company_ref.contact_name}
                  />
                  <ValuePair label="Phone" value={landlord.management_company_ref.contact_phone} />
                  <ValuePair label="Email" value={landlord.management_company_ref.contact_email} />
                  <ValuePair
                    label="Website"
                    value={
                      landlord.management_company_ref.website ? (
                        <Link external href={landlord.management_company_ref.website}>
                          {landlord.management_company_ref.website}
                        </Link>
                      ) : undefined
                    }
                  />
                  <ValuePair
                    label="Online Portal"
                    value={
                      landlord.management_company_ref.portal_url ? (
                        <Link external href={landlord.management_company_ref.portal_url}>
                          {landlord.management_company_ref.portal_url}
                        </Link>
                      ) : undefined
                    }
                  />
                </ColumnLayout>
              ) : (
                <ValuePair label="Management Company" value={landlord.management_company} />
              )}
            </Container>
          )}
          <Container
            header={
              <Header variant="h2" counter={`(${(landlord.owned_offices ?? []).length})`}>
                Owned Offices
              </Header>
            }
          >
            <Table<LandlordOfficeRef>
              columnDefinitions={[
                {
                  id: 'name',
                  header: 'Office',
                  cell: (item) => (
                    <Link onFollow={() => navigate(`/offices/${item.id}`)}>{item.location_name}</Link>
                  ),
                },
              ]}
              items={landlord.owned_offices ?? []}
              empty={
                <Box textAlign="center" color="inherit" padding="m">
                  No offices linked to this landlord.
                </Box>
              }
            />
          </Container>

          {/* Notes */}
          <Container header={<Header variant="h2">Notes</Header>}>
            <Box>{landlord.notes || 'No notes.'}</Box>
          </Container>

          {/* Additional Contacts */}
          {id && <ContactsPanel entityType="landlord" entityId={id} canEdit={canEdit} />}

          {/* Client Portal invite (admin/editor only) */}
          {id && canEdit && <ClientPortalInvitePanel entityType="landlord" entityId={id} />}

          {landlord.additional_names && landlord.additional_names.length > 0 && (
            <Table<LandlordAdditionalName>
              header={<Header variant="h2">Additional Names</Header>}
              columnDefinitions={[
                {
                  id: 'name',
                  header: 'Name',
                  cell: (item) => item.co_name || item.vendor_name || item.other_names || item.additional_names || '—',
                },
                {
                  id: 'other',
                  header: 'Other Names',
                  cell: (item) => item.other_names || '—',
                },
              ]}
              items={landlord.additional_names}
              empty={
                <Box textAlign="center" color="inherit" padding="l">
                  No additional names.
                </Box>
              }
            />
          )}

          {/* Attachments */}
          {id && (
            <AttachmentsPanel
              entityType="landlord"
              entityId={id}
              canEdit={canEdit}
            />
          )}
        </SpaceBetween>
      </ContentLayout>
    </>
  );
};

export default LandlordDetailPage;
