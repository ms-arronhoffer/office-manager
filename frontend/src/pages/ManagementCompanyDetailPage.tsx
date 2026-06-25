import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Link from '@cloudscape-design/components/link';
import { managementCompanies as api } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import ContactsPanel from '@/components/common/ContactsPanel';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import { formatAddress } from '@/components/common/AddressFields';
import type { ManagementCompany } from '@/types';

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value || '—'}</Box>
  </div>
);

const ManagementCompanyDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [company, setCompany] = useState<ManagementCompany | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCompany = useCallback(async () => {
    if (!id) return;
    try {
      const res = await api.get(id);
      setCompany(res.data);
    } catch {
      setError('Failed to load management company details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchCompany();
  }, [fetchCompany]);

  const handleDelete = async () => {
    if (!id || !company) return;
    try {
      await api.delete(id);
      const label = company.name;
      navigate('/management-companies');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button
              variant="link"
              onClick={async () => {
                try {
                  await api.restore(id);
                  navigate(`/management-companies/${id}`);
                } catch {
                  addFlash({ type: 'error', content: 'Failed to undo delete.' });
                }
              }}
            >
              Undo
            </Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete management company.');
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error || !company) {
    return <Alert type="error">{error || 'Management company not found.'}</Alert>;
  }

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Property Management', href: '/management-companies' },
              { text: company.name, href: `/management-companies/${id}` },
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
                  <Button onClick={() => navigate(`/management-companies/${id}/edit`)}>Edit</Button>
                  <Button variant="normal" onClick={handleDelete}>
                    Delete
                  </Button>
                </SpaceBetween>
              ) : undefined
            }
          >
            {company.name}
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Company Information</Header>}>
          <ColumnLayout columns={3} variant="text-grid">
            <ValuePair label="Company Name" value={company.name} />
            <ValuePair label="Primary Contact" value={company.contact_name} />
            <ValuePair label="Contact Title" value={company.contact_title} />
            <ValuePair label="Email" value={company.contact_email} />
            <ValuePair label="Phone" value={company.contact_phone} />
            <ValuePair label="Secondary Phone" value={company.secondary_phone} />
            <ValuePair label="Fax" value={company.fax} />
            <ValuePair
              label="Website"
              value={
                company.website ? (
                  <Link external href={company.website}>
                    {company.website}
                  </Link>
                ) : undefined
              }
            />
            <ValuePair
              label="Online Portal"
              value={
                company.portal_url ? (
                  <Link external href={company.portal_url}>
                    {company.portal_url}
                  </Link>
                ) : undefined
              }
            />
            <ValuePair
              label="Address"
              value={
                <span style={{ whiteSpace: 'pre-line' }}>
                  {formatAddress({
                    address_line_1: company.address_line_1,
                    address_line_2: company.address_line_2,
                    city: company.city,
                    state: company.state,
                    zip_code: company.zip_code,
                  }) || '—'}
                </span>
              }
            />
          </ColumnLayout>
        </Container>

        <Container header={<Header variant="h2">Notes</Header>}>
          <Box>{company.notes || 'No notes.'}</Box>
        </Container>

        {id && (
          <ContactsPanel entityType="management_company" entityId={id} canEdit={canEdit} />
        )}

        {id && <AttachmentsPanel entityType="management_company" entityId={id} canEdit={canEdit} />}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default ManagementCompanyDetailPage;
