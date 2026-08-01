import React, { useCallback, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Spinner from '@cloudscape-design/components/spinner';
import Flashbar from '@cloudscape-design/components/flashbar';
import Tabs from '@cloudscape-design/components/tabs';
import PortalAccessDenied from '@/components/portal/PortalAccessDenied';
import usePortalSession from '@/hooks/usePortalSession';
import { residentPortal } from '@/api';
import type {
  Attachment,
  ResidentPortalAnnouncement,
  ResidentPortalBalance,
  ResidentPortalLease,
  ResidentPortalProfile,
  ResidentPortalTicket,
} from '@/types';

const PRIORITY_OPTIONS = [
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
];

const priorityColor = (p: string): 'red' | 'blue' | 'grey' =>
  p === 'high' ? 'red' : p === 'medium' ? 'blue' : 'grey';

const ticketStatusColor = (s: string): 'green' | 'blue' | 'grey' => {
  if (s === 'closed') return 'green';
  if (s === 'in_progress' || s === 'pending_review') return 'blue';
  return 'grey';
};

const formatMoney = (amount: string | null | undefined, currency: string) => {
  const value = Number(amount ?? 0);
  if (Number.isNaN(value)) return `${amount ?? '—'}`;
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
};

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const formatDate = (d: string | null | undefined) => (d ? d.slice(0, 10) : '—');

const ResidentPortalPage: React.FC = () => {
  const [profile, setProfile] = useState<ResidentPortalProfile | null>(null);
  const [leases, setLeases] = useState<ResidentPortalLease[]>([]);
  const [balance, setBalance] = useState<ResidentPortalBalance | null>(null);
  const [tickets, setTickets] = useState<ResidentPortalTicket[]>([]);
  const [documents, setDocuments] = useState<Attachment[]>([]);
  const [announcements, setAnnouncements] = useState<ResidentPortalAnnouncement[]>([]);

  // Maintenance request modal
  const [requestModal, setRequestModal] = useState(false);
  const [requestForm, setRequestForm] = useState<{ subject: string; description: string; priority: string }>({
    subject: '',
    description: '',
    priority: 'medium',
  });
  const [submitting, setSubmitting] = useState(false);

  const loadData = useCallback(async (activeToken: string) => {
    const [profileRes, leasesRes, balanceRes, ticketsRes, docsRes, annRes] = await Promise.all([
      residentPortal.getProfile(activeToken),
      residentPortal.listLeases(activeToken),
      residentPortal.getBalance(activeToken),
      residentPortal.listMaintenanceRequests(activeToken),
      residentPortal.listDocuments(activeToken),
      residentPortal.listAnnouncements(activeToken),
    ]);
    setProfile(profileRes.data);
    setLeases(leasesRes.data);
    setBalance(balanceRes.data);
    setTickets(ticketsRes.data);
    setDocuments(docsRes.data);
    setAnnouncements(annRes.data);
  }, []);

  const { token, loading, authError, flash, setFlash } = usePortalSession({
    portalPath: '/resident-portal',
    signup: residentPortal.signup,
    load: loadData,
  });

  const openRequest = () => {
    setRequestForm({ subject: '', description: '', priority: 'medium' });
    setRequestModal(true);
  };

  const handleSubmitRequest = async () => {
    if (!requestForm.subject.trim() || !requestForm.description.trim()) {
      setFlash({ type: 'error', content: 'Subject and description are required.' });
      return;
    }
    setSubmitting(true);
    try {
      await residentPortal.createMaintenanceRequest(token, {
        subject: requestForm.subject.trim(),
        description: requestForm.description.trim(),
        priority: requestForm.priority,
      });
      setFlash({ type: 'success', content: 'Maintenance request submitted.' });
      setRequestModal(false);
      const res = await residentPortal.listMaintenanceRequests(token);
      setTickets(res.data);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFlash({ type: 'error', content: detail || 'Failed to submit maintenance request.' });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (authError || !token) {
    return <PortalAccessDenied />;
  }

  const residentName = profile ? `${profile.first_name} ${profile.last_name}`.trim() : '…';
  const currency = balance?.currency ?? leases[0]?.currency ?? 'USD';

  return (
    <ContentLayout
      header={
        <Header variant="h1" description={`Resident portal for ${residentName}`}>
          Resident Portal
        </Header>
      }
    >
      <SpaceBetween size="l">
        {flash && (
          <Flashbar
            items={[
              {
                type: flash.type,
                content: flash.content,
                dismissible: true,
                onDismiss: () => setFlash(null),
                id: 'flash',
              },
            ]}
          />
        )}

        <Tabs
          tabs={[
            {
              id: 'overview',
              label: 'Overview',
              content: (
                <SpaceBetween size="l">
                  <Container header={<Header variant="h2">Account summary</Header>}>
                    <ColumnLayout columns={3} variant="text-grid">
                      <div>
                        <Box variant="awsui-key-label">Monthly rent</Box>
                        <Box variant="awsui-value-large">
                          {formatMoney(balance?.monthly_rent, currency)}
                        </Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Security deposit</Box>
                        <Box variant="awsui-value-large">
                          {formatMoney(balance?.security_deposit, currency)}
                        </Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Balance due</Box>
                        <Box variant="awsui-value-large">
                          {formatMoney(balance?.balance_due, currency)}
                        </Box>
                      </div>
                    </ColumnLayout>
                  </Container>
                  <Container header={<Header variant="h2">Profile</Header>}>
                    <ColumnLayout columns={2} variant="text-grid">
                      <div>
                        <Box variant="awsui-key-label">Name</Box>
                        <div>{residentName || '—'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Status</Box>
                        <div>{profile?.status ?? '—'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Email</Box>
                        <div>{profile?.email ?? '—'}</div>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Phone</Box>
                        <div>{profile?.phone ?? '—'}</div>
                      </div>
                    </ColumnLayout>
                  </Container>
                </SpaceBetween>
              ),
            },
            {
              id: 'leases',
              label: `Leases (${leases.length})`,
              content: (
                <Table
                  items={leases}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No leases on file.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'unit',
                      header: 'Unit',
                      cell: (l: ResidentPortalLease) =>
                        l.unit_number || l.unit_name || l.name || '—',
                    },
                    {
                      id: 'status',
                      header: 'Status',
                      cell: (l: ResidentPortalLease) => (
                        <Badge color={l.status === 'active' ? 'green' : 'grey'}>{l.status}</Badge>
                      ),
                      width: 120,
                    },
                    {
                      id: 'start',
                      header: 'Start',
                      cell: (l: ResidentPortalLease) => formatDate(l.start_date),
                    },
                    {
                      id: 'end',
                      header: 'End',
                      cell: (l: ResidentPortalLease) => formatDate(l.end_date),
                    },
                    {
                      id: 'rent',
                      header: 'Rent',
                      cell: (l: ResidentPortalLease) =>
                        `${formatMoney(l.rent_amount, l.currency)} / ${l.rent_frequency}`,
                    },
                    {
                      id: 'deposit',
                      header: 'Deposit',
                      cell: (l: ResidentPortalLease) => formatMoney(l.security_deposit, l.currency),
                    },
                  ]}
                />
              ),
            },
            {
              id: 'maintenance',
              label: `Maintenance (${tickets.length})`,
              content: (
                <SpaceBetween size="m">
                  <Box float="right">
                    <Button variant="primary" iconName="add-plus" onClick={openRequest}>
                      New request
                    </Button>
                  </Box>
                  <Table
                    items={tickets}
                    empty={
                      <Box textAlign="center" color="inherit">
                        No maintenance requests yet.
                      </Box>
                    }
                    columnDefinitions={[
                      { id: 'subject', header: 'Subject', cell: (t: ResidentPortalTicket) => t.subject },
                      {
                        id: 'priority',
                        header: 'Priority',
                        cell: (t: ResidentPortalTicket) => (
                          <Badge color={priorityColor(t.priority)}>{t.priority}</Badge>
                        ),
                        width: 110,
                      },
                      {
                        id: 'status',
                        header: 'Status',
                        cell: (t: ResidentPortalTicket) => (
                          <Badge color={ticketStatusColor(t.status)}>{t.status}</Badge>
                        ),
                        width: 130,
                      },
                      {
                        id: 'created',
                        header: 'Submitted',
                        cell: (t: ResidentPortalTicket) => formatDate(t.created_at),
                        width: 140,
                      },
                    ]}
                  />
                </SpaceBetween>
              ),
            },
            {
              id: 'documents',
              label: `Documents (${documents.length})`,
              content: (
                <Table
                  items={documents}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No documents available.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'name',
                      header: 'File',
                      cell: (d: Attachment) => d.original_filename,
                    },
                    {
                      id: 'size',
                      header: 'Size',
                      cell: (d: Attachment) => formatBytes(d.file_size),
                      width: 120,
                    },
                    {
                      id: 'created',
                      header: 'Added',
                      cell: (d: Attachment) => formatDate(d.created_at),
                      width: 140,
                    },
                  ]}
                />
              ),
            },
            {
              id: 'announcements',
              label: `Announcements (${announcements.length})`,
              content: (
                <Table
                  items={announcements}
                  empty={
                    <Box textAlign="center" color="inherit">
                      No announcements.
                    </Box>
                  }
                  columnDefinitions={[
                    {
                      id: 'title',
                      header: 'Title',
                      cell: (a: ResidentPortalAnnouncement) => a.title,
                    },
                    {
                      id: 'body',
                      header: 'Message',
                      cell: (a: ResidentPortalAnnouncement) => a.body,
                    },
                    {
                      id: 'sent',
                      header: 'Sent',
                      cell: (a: ResidentPortalAnnouncement) => formatDate(a.sent_at),
                      width: 140,
                    },
                    {
                      id: 'read',
                      header: 'Read',
                      cell: (a: ResidentPortalAnnouncement) =>
                        a.read_at ? <Badge color="green">Read</Badge> : <Badge color="blue">New</Badge>,
                      width: 100,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </SpaceBetween>

      <Modal
        visible={requestModal}
        onDismiss={() => setRequestModal(false)}
        header="New maintenance request"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setRequestModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={submitting} onClick={handleSubmitRequest}>
                Submit
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Subject">
            <Input
              value={requestForm.subject}
              onChange={({ detail }) =>
                setRequestForm((f) => ({ ...f, subject: detail.value }))
              }
              placeholder="e.g. Leaking faucet in kitchen"
            />
          </FormField>
          <FormField label="Description">
            <Textarea
              value={requestForm.description}
              onChange={({ detail }) =>
                setRequestForm((f) => ({ ...f, description: detail.value }))
              }
              placeholder="Describe the issue in detail"
            />
          </FormField>
          <FormField label="Priority">
            <Select
              selectedOption={
                PRIORITY_OPTIONS.find((o) => o.value === requestForm.priority) ?? PRIORITY_OPTIONS[1]
              }
              options={PRIORITY_OPTIONS}
              onChange={({ detail }) =>
                setRequestForm((f) => ({ ...f, priority: detail.selectedOption.value ?? 'medium' }))
              }
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default ResidentPortalPage;
