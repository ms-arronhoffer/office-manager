import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
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
import Textarea from '@cloudscape-design/components/textarea';
import Input from '@cloudscape-design/components/input';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import Flashbar from '@cloudscape-design/components/flashbar';
import Tabs from '@cloudscape-design/components/tabs';
import { vendorPortal } from '@/api';
import type { PortalTicket, VendorPortalProfile } from '@/types';

const priorityColor = (p: string) =>
  p === 'high' ? 'red' : p === 'medium' ? 'blue' : 'grey';

const statusColor = (s: string) => {
  if (s === 'closed') return 'green';
  if (s === 'pending_review') return 'blue';
  if (s === 'in_progress') return 'blue';
  return 'grey';
};

const VendorPortalPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [profile, setProfile] = useState<VendorPortalProfile | null>(null);
  const [tickets, setTickets] = useState<PortalTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);
  const [flash, setFlash] = useState<{ type: 'success' | 'error'; content: string } | null>(null);

  // Complete modal
  const [completeTicket, setCompleteTicket] = useState<PortalTicket | null>(null);
  const [completionNotes, setCompletionNotes] = useState('');
  const [completing, setCompleting] = useState(false);

  // Profile edit
  const [editingProfile, setEditingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState<Partial<VendorPortalProfile>>({});
  const [savingProfile, setSavingProfile] = useState(false);

  const load = useCallback(async () => {
    if (!token) {
      setAuthError(true);
      setLoading(false);
      return;
    }
    try {
      const [profileRes, ticketsRes] = await Promise.all([
        vendorPortal.getProfile(token),
        vendorPortal.listTickets(token),
      ]);
      setProfile(profileRes.data);
      setTickets(ticketsRes.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        setAuthError(true);
      } else {
        setFlash({ type: 'error', content: 'Failed to load portal data.' });
      }
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleComplete = async () => {
    if (!completeTicket || !completionNotes.trim()) return;
    setCompleting(true);
    try {
      await vendorPortal.completeTicket(token, completeTicket.id, completionNotes);
      setFlash({ type: 'success', content: 'Work marked as complete. Your client will review shortly.' });
      setCompleteTicket(null);
      setCompletionNotes('');
      await load();
    } catch {
      setFlash({ type: 'error', content: 'Failed to submit completion.' });
    } finally {
      setCompleting(false);
    }
  };

  const openProfileEdit = () => {
    if (!profile) return;
    setProfileForm({
      contact_name: profile.contact_name ?? '',
      contact_email: profile.contact_email ?? '',
      contact_phone: profile.contact_phone ?? '',
      address_line_1: profile.address_line_1 ?? '',
      address_line_2: profile.address_line_2 ?? '',
      city: profile.city ?? '',
      state: profile.state ?? '',
      zip_code: profile.zip_code ?? '',
    });
    setEditingProfile(true);
  };

  const handleSaveProfile = async () => {
    setSavingProfile(true);
    try {
      const res = await vendorPortal.updateProfile(token, profileForm);
      setProfile(res.data);
      setFlash({ type: 'success', content: 'Profile updated.' });
      setEditingProfile(false);
    } catch {
      setFlash({ type: 'error', content: 'Failed to update profile.' });
    } finally {
      setSavingProfile(false);
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
    return (
      <Box padding="xxl">
        <Alert type="error" header="Access denied">
          This vendor portal link is invalid or has expired. Please contact your client for a new link.
        </Alert>
      </Box>
    );
  }

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description={`Vendor portal for ${profile?.company_name ?? '…'}`}
        >
          Vendor Work Portal
        </Header>
      }
    >
      <SpaceBetween size="l">
        {flash && (
          <Flashbar
            items={[{
              type: flash.type,
              content: flash.content,
              dismissible: true,
              onDismiss: () => setFlash(null),
              id: 'flash',
            }]}
          />
        )}

        <Tabs
          tabs={[
            {
              id: 'tickets',
              label: `Work Orders (${tickets.length})`,
              content: (
                <Table
                  items={tickets}
                  columnDefinitions={[
                    {
                      id: 'subject',
                      header: 'Subject',
                      cell: (t: PortalTicket) => t.subject,
                    },
                    {
                      id: 'office',
                      header: 'Location',
                      cell: (t: PortalTicket) => t.office?.location_name ?? '—',
                    },
                    {
                      id: 'priority',
                      header: 'Priority',
                      cell: (t: PortalTicket) => (
                        <Badge color={priorityColor(t.priority)}>{t.priority.toUpperCase()}</Badge>
                      ),
                      width: 100,
                    },
                    {
                      id: 'status',
                      header: 'Status',
                      cell: (t: PortalTicket) => (
                        <Badge color={statusColor(t.status)}>{t.status.replace(/_/g, ' ').toUpperCase()}</Badge>
                      ),
                      width: 140,
                    },
                    {
                      id: 'actions',
                      header: '',
                      cell: (t: PortalTicket) =>
                        !t.vendor_completed_at ? (
                          <Button
                            variant="primary"
                            onClick={() => { setCompleteTicket(t); setCompletionNotes(''); }}
                          >
                            Mark complete
                          </Button>
                        ) : (
                          <Box color="text-status-success">Completed</Box>
                        ),
                      width: 160,
                    },
                  ]}
                  empty={
                    <Box textAlign="center" padding="l">
                      <b>No work orders assigned</b>
                      <Box color="text-body-secondary" padding={{ bottom: 's' }}>
                        Your assigned work orders will appear here.
                      </Box>
                    </Box>
                  }
                  header={<Header>Assigned Work Orders</Header>}
                />
              ),
            },
            {
              id: 'profile',
              label: 'Your Profile',
              content: profile ? (
                <Container
                  header={
                    <Header
                      variant="h2"
                      actions={<Button onClick={openProfileEdit}>Edit profile</Button>}
                    >
                      Contact Information
                    </Header>
                  }
                >
                  <ColumnLayout columns={3} variant="text-grid">
                    {[
                      ['Company', profile.company_name],
                      ['Contact name', profile.contact_name],
                      ['Email', profile.contact_email],
                      ['Phone', profile.contact_phone],
                      ['Address', [profile.address_line_1, profile.city, profile.state, profile.zip_code].filter(Boolean).join(', ')],
                      ['Services', profile.services],
                    ].map(([label, value]) => (
                      <div key={label as string}>
                        <Box variant="awsui-key-label">{label}</Box>
                        <Box>{(value as string) || '—'}</Box>
                      </div>
                    ))}
                  </ColumnLayout>
                </Container>
              ) : null,
            },
          ]}
        />
      </SpaceBetween>

      {/* ── Complete Ticket Modal ── */}
      <Modal
        visible={!!completeTicket}
        onDismiss={() => setCompleteTicket(null)}
        header="Mark work complete"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setCompleteTicket(null)}>Cancel</Button>
              <Button
                variant="primary"
                loading={completing}
                disabled={!completionNotes.trim()}
                onClick={handleComplete}
              >
                Submit completion
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box>
            <Box variant="awsui-key-label">Work order</Box>
            <Box>{completeTicket?.subject}</Box>
          </Box>
          <FormField label="Completion notes" description="Describe the work performed, materials used, and any follow-up needed.">
            <Textarea
              value={completionNotes}
              onChange={({ detail }) => setCompletionNotes(detail.value)}
              placeholder="Describe the work completed..."
              rows={5}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* ── Profile Edit Modal ── */}
      <Modal
        visible={editingProfile}
        onDismiss={() => setEditingProfile(false)}
        header="Edit profile"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setEditingProfile(false)}>Cancel</Button>
              <Button variant="primary" loading={savingProfile} onClick={handleSaveProfile}>Save</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Contact name">
              <Input
                value={profileForm.contact_name ?? ''}
                onChange={({ detail }) => setProfileForm((f) => ({ ...f, contact_name: detail.value }))}
              />
            </FormField>
            <FormField label="Contact email">
              <Input
                value={profileForm.contact_email ?? ''}
                onChange={({ detail }) => setProfileForm((f) => ({ ...f, contact_email: detail.value }))}
                type="email"
              />
            </FormField>
          </SpaceBetween>
          <FormField label="Phone">
            <Input
              value={profileForm.contact_phone ?? ''}
              onChange={({ detail }) => setProfileForm((f) => ({ ...f, contact_phone: detail.value }))}
              type="tel"
            />
          </FormField>
          <FormField label="Address line 1">
            <Input
              value={profileForm.address_line_1 ?? ''}
              onChange={({ detail }) => setProfileForm((f) => ({ ...f, address_line_1: detail.value }))}
            />
          </FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="City">
              <Input
                value={profileForm.city ?? ''}
                onChange={({ detail }) => setProfileForm((f) => ({ ...f, city: detail.value }))}
              />
            </FormField>
            <FormField label="State">
              <Input
                value={profileForm.state ?? ''}
                onChange={({ detail }) => setProfileForm((f) => ({ ...f, state: detail.value }))}
                placeholder="NY"
              />
            </FormField>
            <FormField label="ZIP">
              <Input
                value={profileForm.zip_code ?? ''}
                onChange={({ detail }) => setProfileForm((f) => ({ ...f, zip_code: detail.value }))}
              />
            </FormField>
          </SpaceBetween>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default VendorPortalPage;
