import React, { useEffect, useState } from 'react';
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
import { hvacContracts as hvacContractsApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import type { HvacContract } from '@/types';

const formatDate = (dateStr?: string | null): string => {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
};

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value ?? '—'}</Box>
  </div>
);

const HvacContractDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();
  const [contract, setContract] = useState<HvacContract | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const fetchContract = async () => {
      try {
        const res = await hvacContractsApi.get(id);
        setContract(res.data);
      } catch {
        setError('Failed to load HVAC contract details.');
      } finally {
        setLoading(false);
      }
    };
    fetchContract();
  }, [id]);

  const handleDelete = async () => {
    if (!id || !contract) return;
    try {
      await hvacContractsApi.delete(id);
      const label = contract.hvac_company || 'HVAC contract';
      navigate('/hvac-contracts');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button variant="link" onClick={async () => {
              try {
                await hvacContractsApi.restore(id);
                navigate(`/hvac-contracts/${id}`);
              } catch {
                addFlash({ type: 'error', content: 'Failed to undo delete.' });
              }
            }}>Undo</Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete HVAC contract.');
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error || !contract) {
    return <Alert type="error">{error || 'HVAC contract not found.'}</Alert>;
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
                { text: 'HVAC Contracts', href: '/hvac-contracts' },
                {
                  text: contract.hvac_company || 'HVAC Contract',
                  href: `/hvac-contracts/${id}`,
                },
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
                  <Button onClick={() => navigate(`/hvac-contracts/${id}/edit`)}>Edit</Button>
                  <Button onClick={() => confirmDelete({ itemName: contract.hvac_company || 'HVAC Contract', onConfirm: handleDelete })}>Delete</Button>
                </SpaceBetween>
              }
            >
              {contract.hvac_company || 'HVAC Contract'}
            </Header>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="l">
          {/* Main contract details */}
          <Container header={<Header variant="h2">Contract Details</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <ValuePair label="HVAC Company" value={contract.hvac_company} />
              <ValuePair label="Contact" value={contract.contact} />
              <ValuePair
                label="Office"
                value={contract.office_name || (contract.office_number != null ? `#${contract.office_number}` : undefined)}
              />
              <ValuePair label="Manager" value={contract.manager?.name} />
              <ValuePair
                label="Landlord Handles"
                value={
                  <StatusIndicator type={contract.landlord_handles ? 'success' : 'stopped'}>
                    {contract.landlord_handles ? 'Yes' : 'No'}
                  </StatusIndicator>
                }
              />
              <ValuePair label="Frequency" value={contract.frequency} />
              <ValuePair
                label="Last Serviced"
                value={contract.last_serviced_date ? formatDate(contract.last_serviced_date) : contract.last_serviced}
              />
              <ValuePair
                label="Next Service"
                value={contract.next_service_date ? formatDate(contract.next_service_date) : contract.next_service}
              />
            </ColumnLayout>
            {contract.comments && (
              <Box margin={{ top: 'm' }}>
                <Box variant="awsui-key-label">Comments</Box>
                <Box>{contract.comments}</Box>
              </Box>
            )}
          </Container>

          {/* Office details list (per-office HVAC sheet rows) */}
          {contract.details && contract.details.length > 0 && (
            <Container header={<Header variant="h2">Office Detail Sheets</Header>}>
              <SpaceBetween size="m">
                {contract.details.map((d) => (
                  <Container key={d.id} header={<Header variant="h3">{d.sheet_name || 'Sheet'}</Header>}>
                    <ColumnLayout columns={2} variant="text-grid">
                      <ValuePair label="Contractor" value={d.hvac_contractor} />
                      <ValuePair label="Frequency" value={d.frequency} />
                      <ValuePair label="Lease Expiration" value={formatDate(d.lease_expiration) || d.lease_expiration_text} />
                      <ValuePair label="Responsibility" value={d.responsibility_summary} />
                    </ColumnLayout>
                    {d.responsibility_detail && (
                      <Box margin={{ top: 's' }}>
                        <Box variant="awsui-key-label">Detail</Box>
                        <Box>{d.responsibility_detail}</Box>
                      </Box>
                    )}
                  </Container>
                ))}
              </SpaceBetween>
            </Container>
          )}

          {/* Attachments */}
          {id && (
            <AttachmentsPanel
              entityType="hvac_contract"
              entityId={id}
              canEdit={user?.role === 'admin' || user?.role === 'editor'}
            />
          )}
        </SpaceBetween>
      </ContentLayout>
    </>
  );
};

export default HvacContractDetailPage;
