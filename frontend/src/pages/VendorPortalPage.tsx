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
import type { PortalTicket, VendorPortalProfile, EntityContact, EntityContactCreate } from '@/types';

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
  const [contacts, setContacts] = useState<EntityContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);
  const [flash, setFlash] = useState<{ type: 'success' | 'error'; content: string } | null>(null);

  // Complete modal
  const [completeTicket, setCompleteTicket] = useState<PortalTicket | null>(null);
  const [completionNotes, setCompletionNotes] = useState('');
  const [completing, setCompleting] = useState(false);

  // Ticket details edit modal
  const [editTicket, setEditTicket] = useState<PortalTicket | null>(null);
  const [ticketForm, setTicketForm] = useState<{
    description: string;
    location_hours: string;
    technician_name: string;
    scheduled_date: string;
    estimated_duration_minutes: string;
  }>({
    description: '',
    location_hours: '',
    technician_name: '',
    scheduled_date: '',
    estimated_duration_minutes: '',
  });
  const [savingTicket, setSavingTicket] = useState(false);

  // Contact modal
  const [contactModalOpen, setContactModalOpen] = useState(false);
  const [editingContact, setEditingContact] = useState<EntityContact | null>(null);
  const [contactForm, setContactForm] = useState<{
    contact_name: string;
    title: string;
    email: string;
    phone: string;
    mobile: string;
    notes: string;
  }>({ contact_name: '', title: '', email: '', phone: '', mobile: '', notes: '' });
  const [savingContact, setSavingContact] = useState(false);

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
      const [profileRes, ticketsRes, contactsRes] = await Promise.all([
        vendorPortal.getProfile(token),
        vendorPortal.listTickets(token),
        vendorPortal.listContacts(token),
      ]);
      setProfile(profileRes.data);
      setTickets(ticketsRes.data);
      setContacts(contactsRes.data);
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

  const openEditTicket = (t: PortalTicket) => {
    setEditTicket(t);
    setTicketForm({
      description: t.description ?? '',
      location_hours: t.location_hours ?? '',
      technician_name: t.technician_name ?? '',
      scheduled_date: t.scheduled_date ? t.scheduled_date.slice(0, 16) : '',
      estimated_duration_minutes:
        t.estimated_duration_minutes != null ? String(t.estimated_duration_minutes) : '',
    });
  };

  const handleSaveTicket = async () => {
    if (!editTicket) return;
    setSavingTicket(true);
    try {
      await vendorPortal.updateTicket(token, editTicket.id, {
        description: ticketForm.description,
        location_hours: ticketForm.location_hours || undefined,
        technician_name: ticketForm.technician_name || undefined,
        scheduled_date: ticketForm.scheduled_date
          ? new Date(ticketForm.scheduled_date).toISOString()
          : null,
        estimated_duration_minutes: ticketForm.estimated_duration_minutes
          ? parseInt(ticketForm.estimated_duration_minutes, 10)
          : null,
      });
      setFlash({ type: 'success', content: 'Work order details updated.' });
      setEditTicket(null);
      await load();
    } catch {
      setFlash({ type: 'error', content: 'Failed to update work order.' });
    } finally {
      setSavingTicket(false);
    }
  };

  const openCreateContact = () => {
    setEditingContact(null);
    setContactForm({ contact_name: '', title: '', email: '', phone: '', mobile: '', notes: '' });
    setContactModalOpen(true);
  };

  const openEditContact = (c: EntityContact) => {
    setEditingContact(c);
    setContactForm({
      contact_name: c.contact_name ?? '',
      title: c.title ?? '',
      email: c.email ?? '',
      phone: c.phone ?? '',
      mobile: c.mobile ?? '',
      notes: c.notes ?? '',
    });
    setContactModalOpen(true);
  };

  const handleSaveContact = async () => {
    if (!contactForm.contact_name.trim()) return;
    setSavingContact(true);
    try {
      const payload = {
        contact_name: contactForm.contact_name.trim(),
        title: contactForm.title || undefined,
        email: contactForm.email || undefined,
        phone: contactForm.phone || undefined,
        mobile: contactForm.mobile || undefined,
        notes: contactForm.notes || undefined,
      };
      if (editingContact) {
        await vendorPortal.updateContact(token, editingContact.id, payload);
      } else {
        // entity_type/entity_id are enforced server-side from the token.
        await vendorPortal.createContact(token, {
          entity_type: 'vendor',
          entity_id: profile?.id ?? '',
          ...payload,
        } as EntityContactCreate);
      }
      setFlash({ type: 'success', content: 'Contact saved.' });
      setContactModalOpen(false);
      await load();
    } catch {
      setFlash({ type: 'error', content: 'Failed to save contact.' });
    } finally {
      setSavingContact(false);
    }
  };

  const handleDeleteContact = async (c: EntityContact) => {
    try {
      await vendorPortal.deleteContact(token, c.id);
      setFlash({ type: 'success', content: 'Contact removed.' });
      await load();
    } catch {
      setFlash({ type: 'error', content: 'Failed to remove contact.' });
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
                      cell: (t: PortalTicket) => (
                        <SpaceBetween direction="horizontal" size="xs">
                          <Button onClick={() => openEditTicket(t)}>Edit details</Button>
                          {!t.vendor_completed_at ? (
                            <Button
                              variant="primary"
                              onClick={() => { setCompleteTicket(t); setCompletionNotes(''); }}
                            >
                              Mark complete
                            </Button>
                          ) : (
                            <Box color="text-status-success">Completed</Box>
                          )}
                        </SpaceBetween>
                      ),
                      width: 280,
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
              id: 'contacts',
              label: `Contacts (${contacts.length})`,
              content: (
                <Table
                  items={contacts}
                  columnDefinitions={[
                    {
                      id: 'name',
                      header: 'Name',
                      cell: (c: EntityContact) => c.contact_name,
                    },
                    {
                      id: 'title',
                      header: 'Title',
                      cell: (c: EntityContact) => c.title ?? '—',
                    },
                    {
                      id: 'email',
                      header: 'Email',
                      cell: (c: EntityContact) => c.email ?? '—',
                    },
                    {
                      id: 'phone',
                      header: 'Phone',
                      cell: (c: EntityContact) => c.phone ?? c.mobile ?? '—',
                    },
                    {
                      id: 'actions',
                      header: '',
                      cell: (c: EntityContact) => (
                        <SpaceBetween direction="horizontal" size="xs">
                          <Button onClick={() => openEditContact(c)}>Edit</Button>
                          <Button onClick={() => handleDeleteContact(c)}>Remove</Button>
                        </SpaceBetween>
                      ),
                      width: 180,
                    },
                  ]}
                  empty={
                    <Box textAlign="center" padding="l">
                      <b>No additional contacts</b>
                      <Box color="text-body-secondary" padding={{ bottom: 's' }}>
                        Add the people your client should reach for this work.
                      </Box>
                    </Box>
                  }
                  header={
                    <Header
                      actions={<Button onClick={openCreateContact}>Add contact</Button>}
                    >
                      Additional Contacts
                    </Header>
                  }
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

      {/* ── Edit Ticket Details Modal ── */}
      <Modal
        visible={!!editTicket}
        onDismiss={() => setEditTicket(null)}
        header="Edit work order details"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setEditTicket(null)}>Cancel</Button>
              <Button variant="primary" loading={savingTicket} onClick={handleSaveTicket}>Save</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box>
            <Box variant="awsui-key-label">Work order</Box>
            <Box>{editTicket?.subject}</Box>
          </Box>
          <FormField label="Description">
            <Textarea
              value={ticketForm.description}
              onChange={({ detail }) => setTicketForm((f) => ({ ...f, description: detail.value }))}
              rows={5}
            />
          </FormField>
          <FormField label="Location hours / schedule">
            <Input
              value={ticketForm.location_hours}
              onChange={({ detail }) => setTicketForm((f) => ({ ...f, location_hours: detail.value }))}
              placeholder="e.g., Mon-Fri 8am-5pm"
            />
          </FormField>
          <FormField label="Technician name">
            <Input
              value={ticketForm.technician_name}
              onChange={({ detail }) => setTicketForm((f) => ({ ...f, technician_name: detail.value }))}
            />
          </FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Scheduled date">
              <Input
                type="datetime-local"
                value={ticketForm.scheduled_date}
                onChange={({ detail }) => setTicketForm((f) => ({ ...f, scheduled_date: detail.value }))}
              />
            </FormField>
            <FormField label="Estimated duration (minutes)">
              <Input
                type="number"
                value={ticketForm.estimated_duration_minutes}
                onChange={({ detail }) =>
                  setTicketForm((f) => ({ ...f, estimated_duration_minutes: detail.value }))
                }
                placeholder="e.g. 120"
              />
            </FormField>
          </SpaceBetween>
        </SpaceBetween>
      </Modal>

      {/* ── Contact Modal ── */}
      <Modal
        visible={contactModalOpen}
        onDismiss={() => setContactModalOpen(false)}
        header={editingContact ? 'Edit contact' : 'Add contact'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setContactModalOpen(false)}>Cancel</Button>
              <Button
                variant="primary"
                loading={savingContact}
                disabled={!contactForm.contact_name.trim()}
                onClick={handleSaveContact}
              >
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Name">
              <Input
                value={contactForm.contact_name}
                onChange={({ detail }) => setContactForm((f) => ({ ...f, contact_name: detail.value }))}
              />
            </FormField>
            <FormField label="Title">
              <Input
                value={contactForm.title}
                onChange={({ detail }) => setContactForm((f) => ({ ...f, title: detail.value }))}
              />
            </FormField>
          </SpaceBetween>
          <FormField label="Email">
            <Input
              type="email"
              value={contactForm.email}
              onChange={({ detail }) => setContactForm((f) => ({ ...f, email: detail.value }))}
            />
          </FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Phone">
              <Input
                type="tel"
                value={contactForm.phone}
                onChange={({ detail }) => setContactForm((f) => ({ ...f, phone: detail.value }))}
              />
            </FormField>
            <FormField label="Mobile">
              <Input
                type="tel"
                value={contactForm.mobile}
                onChange={({ detail }) => setContactForm((f) => ({ ...f, mobile: detail.value }))}
              />
            </FormField>
          </SpaceBetween>
          <FormField label="Notes">
            <Textarea
              value={contactForm.notes}
              onChange={({ detail }) => setContactForm((f) => ({ ...f, notes: detail.value }))}
              rows={3}
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
