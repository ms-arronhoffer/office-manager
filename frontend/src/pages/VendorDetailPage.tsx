import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Input from '@cloudscape-design/components/input';
import { vendors as vendorsApi, vendorPortalInternal } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import ContactsPanel from '@/components/common/ContactsPanel';
import { formatAddress } from '@/components/common/AddressFields';
import type { Vendor } from '@/types';

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value || '—'}</Box>
  </div>
);

const VendorDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [vendor, setVendor] = useState<Vendor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [portalLink, setPortalLink] = useState<string | null>(null);
  const [generatingToken, setGeneratingToken] = useState(false);

  const fetchVendor = useCallback(async () => {
    if (!id) return;
    try {
      const res = await vendorsApi.get(id);
      setVendor(res.data);
    } catch {
      setError('Failed to load vendor details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchVendor();
  }, [fetchVendor]);

  const generatePortalToken = async () => {
    if (!id) return;
    setGeneratingToken(true);
    try {
      const res = await vendorPortalInternal.generateToken(id);
      const fullUrl = `${window.location.origin}${res.data.portal_url}`;
      setPortalLink(fullUrl);
      addFlash({ type: 'success', content: 'Portal link generated. Copy it and share with the vendor.' });
    } catch {
      addFlash({ type: 'error', content: 'Failed to generate portal link.' });
    } finally {
      setGeneratingToken(false);
    }
  };

  const handleDelete = async () => {
    if (!id || !vendor) return;
    try {
      await vendorsApi.delete(id);
      const label = vendor.company_name;
      navigate('/vendors');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button variant="link" onClick={async () => {
              try {
                await vendorsApi.restore(id);
                navigate(`/vendors/${id}`);
              } catch {
                addFlash({ type: 'error', content: 'Failed to undo delete.' });
              }
            }}>Undo</Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete vendor.');
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error || !vendor) {
    return <Alert type="error">{error || 'Vendor not found.'}</Alert>;
  }

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Vendors', href: '/vendors' },
              { text: vendor.company_name, href: `/vendors/${id}` },
            ]}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
          <Header
            variant="h1"
            actions={
              canEdit ? (
                <SpaceBetween direction="horizontal" size="xs">
                  <Button onClick={() => navigate(`/vendors/${id}/edit`)}>Edit</Button>
                  <Button variant="normal" onClick={handleDelete}>Delete</Button>
                </SpaceBetween>
              ) : undefined
            }
          >
            {vendor.company_name}
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Vendor Information</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <ValuePair label="Company Name" value={vendor.company_name} />
            <ValuePair label="Services" value={vendor.services} />
            <ValuePair
              label="Preferred Vendor"
              value={
                <StatusIndicator type={vendor.is_preferred ? 'success' : 'stopped'}>
                  {vendor.is_preferred ? 'Yes' : 'No'}
                </StatusIndicator>
              }
            />
            <ValuePair label="Contact Name" value={vendor.contact_name} />
            <ValuePair label="Email" value={vendor.contact_email} />
            <ValuePair label="Phone" value={vendor.contact_phone} />
            <ValuePair
              label="Address"
              value={
                <Box>
                  <span style={{ whiteSpace: 'pre-line' }}>
                    {formatAddress(
                      {
                        address_line_1: vendor.address_line_1,
                        address_line_2: vendor.address_line_2,
                        city: vendor.city,
                        state: vendor.state,
                        zip_code: vendor.zip_code,
                      },
                      vendor.address,
                    )}
                  </span>
                </Box>
              }
            />
          </ColumnLayout>
        </Container>

        <Container header={<Header variant="h2">Assigned Offices</Header>}>
          {vendor.offices?.length ? (
            <SpaceBetween size="xs">
              {vendor.offices.map((o) => (
                <Box key={o.id}>
                  <Button variant="link" onClick={() => navigate(`/offices/${o.id}`)}>
                    {o.location_name}
                  </Button>
                </Box>
              ))}
            </SpaceBetween>
          ) : (
            <Box color="text-status-inactive">No offices assigned.</Box>
          )}
        </Container>

        <Container header={<Header variant="h2">Notes</Header>}>
          <Box>{vendor.notes || 'No notes.'}</Box>
        </Container>

        {canEdit && (
          <Container
            header={
              <Header
                variant="h2"
                actions={
                  <Button
                    variant="normal"
                    loading={generatingToken}
                    onClick={generatePortalToken}
                  >
                    {portalLink ? 'Regenerate link' : 'Generate portal link'}
                  </Button>
                }
              >
                Vendor Portal Access
              </Header>
            }
          >
            <SpaceBetween size="s">
              <Box color="text-body-secondary">
                Generate a secure link to share with the vendor. They can use it to view assigned work orders, submit completion notes, and update their contact information — without needing an account.
              </Box>
              {portalLink && (
                <SpaceBetween direction="horizontal" size="xs">
                  <Input value={portalLink} readOnly onChange={() => {}} />
                  <Button
                    iconName="copy"
                    variant="normal"
                    onClick={() => navigator.clipboard.writeText(portalLink)}
                  >
                    Copy
                  </Button>
                </SpaceBetween>
              )}
            </SpaceBetween>
          </Container>
        )}

        {id && (
          <ContactsPanel entityType="vendor" entityId={id} canEdit={canEdit} />
        )}

        {id && (
          <AttachmentsPanel
            entityType="vendor"
            entityId={id}
            canEdit={canEdit}
          />
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default VendorDetailPage;
