import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useConfirmDelete } from '@/hooks/useConfirmDelete';
import { useSearchParams, useLocation, useNavigate } from 'react-router-dom';
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
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import Flashbar from '@cloudscape-design/components/flashbar';
import Tabs from '@cloudscape-design/components/tabs';
import type { InputProps } from '@cloudscape-design/components/input';
import { clientPortal } from '@/api';
import type {
  ClientPortalProfile,
  ClientPortalChangeRequest,
  EntityContact,
  EntityContactCreate,
  Attachment,
  ClientPortalSummary,
  ClientPortalOffice,
  ClientPortalLease,
  ClientPortalTicket,
} from '@/types';

const formatBytes = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const entityLabel = (t?: string) =>
  t === 'management_company' ? 'Management Company' : 'Landlord';

// Profile fields a client may propose corrections to (mirrors the backend
// whitelist in client_portal.py).
const CHANGE_REQUEST_FIELDS: { key: string; label: string }[] = [
  { key: 'contact_name', label: 'Primary contact' },
  { key: 'contact_email', label: 'Email' },
  { key: 'contact_phone', label: 'Phone' },
  { key: 'website', label: 'Website' },
  { key: 'address_line_1', label: 'Address line 1' },
  { key: 'address_line_2', label: 'Address line 2' },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'State' },
  { key: 'zip_code', label: 'ZIP code' },
];

const changeRequestStatusColor = (
  s: ClientPortalChangeRequest['status'],
): 'blue' | 'green' | 'red' => {
  if (s === 'approved') return 'green';
  if (s === 'rejected') return 'red';
  return 'blue';
};

const fieldLabel = (key: string) =>
  CHANGE_REQUEST_FIELDS.find((f) => f.key === key)?.label ?? key;

const summarizeChanges = (changes: Record<string, string | null>) =>
  Object.entries(changes)
    .map(([k, v]) => `${fieldLabel(k)}: ${v ?? '(blank)'}`)
    .join(', ');

type ContactForm = {
  contact_name: string;
  title: string;
  email: string;
  phone: string;
  mobile: string;
  notes: string;
};

const emptyContactForm: ContactForm = {
  contact_name: '',
  title: '',
  email: '',
  phone: '',
  mobile: '',
  notes: '',
};

const ClientPortalPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  // The single-use invite lands on /client-portal/signup?token=...; the
  // persistent portal link is /client-portal?token=...
  const isSignupRoute = location.pathname.endsWith('/signup');
  const urlToken = searchParams.get('token') ?? '';
  const signupToken = isSignupRoute ? urlToken : '';
  const tokenParam = isSignupRoute ? '' : urlToken;

  const [token, setToken] = useState(tokenParam);
  const [profile, setProfile] = useState<ClientPortalProfile | null>(null);
  const [contacts, setContacts] = useState<EntityContact[]>([]);
  const [documents, setDocuments] = useState<Attachment[]>([]);
  const [changeRequests, setChangeRequests] = useState<ClientPortalChangeRequest[]>([]);
  const [summary, setSummary] = useState<ClientPortalSummary | null>(null);
  const [offices, setOffices] = useState<ClientPortalOffice[]>([]);
  const [leases, setLeases] = useState<ClientPortalLease[]>([]);
  const [tickets, setTickets] = useState<ClientPortalTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(false);
  const [flash, setFlash] = useState<{ type: 'success' | 'error'; content: string } | null>(null);

  // Contact modal
  const [contactModal, setContactModal] = useState(false);
  const { confirmDelete, modal: deleteModal } = useConfirmDelete();
  const [editingContact, setEditingContact] = useState<EntityContact | null>(null);
  const [contactForm, setContactForm] = useState<ContactForm>(emptyContactForm);
  const [contactNameError, setContactNameError] = useState('');
  const [savingContact, setSavingContact] = useState(false);
  const contactNameRef = useRef<InputProps.Ref>(null);

  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  // Change-request modal
  const [crModal, setCrModal] = useState(false);
  const [crFields, setCrFields] = useState<Record<string, string>>({});
  const [crMessage, setCrMessage] = useState('');
  const [savingCr, setSavingCr] = useState(false);

  // Redeem a one-time signup token (if present) before loading data.
  const redeemSignup = useCallback(async () => {
    try {
      const res = await clientPortal.signup(signupToken);
      const newToken = res.data.portal_token;
      setToken(newToken);
      // Swap the single-use signup link for the persistent portal link.
      navigate(`/client-portal?token=${newToken}`, { replace: true });
      return newToken;
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 410) {
        setFlash({ type: 'error', content: 'This signup link has expired. Please request a new one.' });
      }
      setAuthError(true);
      return '';
    }
  }, [signupToken, navigate]);

  const loadData = useCallback(async (activeToken: string) => {
    try {
      const [profileRes, contactsRes, docsRes, crRes, summaryRes, officesRes, leasesRes, ticketsRes] = await Promise.all([
        clientPortal.getProfile(activeToken),
        clientPortal.listContacts(activeToken),
        clientPortal.listDocuments(activeToken),
        clientPortal.listChangeRequests(activeToken),
        clientPortal.summary(activeToken),
        clientPortal.listOffices(activeToken),
        clientPortal.listLeases(activeToken),
        clientPortal.listMaintenance(activeToken),
      ]);
      setProfile(profileRes.data);
      setContacts(contactsRes.data);
      setDocuments(docsRes.data);
      setChangeRequests(crRes.data);
      setSummary(summaryRes.data);
      setOffices(officesRes.data);
      setLeases(leasesRes.data);
      setTickets(ticketsRes.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        setAuthError(true);
      } else {
        setFlash({ type: 'error', content: 'Failed to load portal data.' });
      }
    }
  }, []);

  const init = useCallback(async () => {
    setLoading(true);
    let activeToken = tokenParam;
    if (signupToken) {
      activeToken = await redeemSignup();
    }
    if (!activeToken) {
      setAuthError(true);
      setLoading(false);
      return;
    }
    await loadData(activeToken);
    setLoading(false);
  }, [tokenParam, signupToken, redeemSignup, loadData]);

  useEffect(() => {
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openCreateContact = () => {
    setEditingContact(null);
    setContactForm(emptyContactForm);
    setContactNameError('');
    setContactModal(true);
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
    setContactNameError('');
    setContactModal(true);
  };

  const handleSaveContact = async () => {
    if (!contactForm.contact_name.trim()) {
      setContactNameError('Contact name is required.');
      contactNameRef.current?.focus();
      return;
    }
    setSavingContact(true);
    try {
      const payload: Omit<EntityContactCreate, 'entity_type' | 'entity_id'> = {
        contact_name: contactForm.contact_name.trim(),
        title: contactForm.title || undefined,
        email: contactForm.email || undefined,
        phone: contactForm.phone || undefined,
        mobile: contactForm.mobile || undefined,
        notes: contactForm.notes || undefined,
      };
      if (editingContact) {
        await clientPortal.updateContact(token, editingContact.id, payload);
      } else {
        // entity_type/entity_id are forced server-side from the portal account.
        await clientPortal.createContact(token, payload as EntityContactCreate);
      }
      setFlash({ type: 'success', content: 'Contact saved.' });
      setContactModal(false);
      const res = await clientPortal.listContacts(token);
      setContacts(res.data);
    } catch {
      setFlash({ type: 'error', content: 'Failed to save contact.' });
    } finally {
      setSavingContact(false);
    }
  };

  const handleDeleteContact = async (c: EntityContact) => {
    try {
      await clientPortal.deleteContact(token, c.id);
      setContacts((prev) => prev.filter((x) => x.id !== c.id));
      setFlash({ type: 'success', content: 'Contact removed.' });
    } catch {
      setFlash({ type: 'error', content: 'Failed to remove contact.' });
    }
  };

  const uploadFile = async (file: File) => {
    setUploading(true);
    try {
      await clientPortal.uploadDocument(token, file);
      setFlash({ type: 'success', content: 'Document uploaded.' });
      const res = await clientPortal.listDocuments(token);
      setDocuments(res.data);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFlash({ type: 'error', content: detail || 'Failed to upload document.' });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadFile(file);
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) await uploadFile(file);
  };

  const handleDownload = async (d: Attachment) => {
    try {
      const res = await clientPortal.downloadDocument(token, d.id);
      const url = window.URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = d.original_filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      setFlash({ type: 'error', content: 'Failed to download document.' });
    }
  };

  const handleDeleteDocument = async (d: Attachment) => {
    try {
      await clientPortal.deleteDocument(token, d.id);
      setDocuments((prev) => prev.filter((x) => x.id !== d.id));
      setFlash({ type: 'success', content: 'Document removed.' });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFlash({ type: 'error', content: detail || 'Failed to remove document.' });
    }
  };

  const openChangeRequest = () => {
    setCrFields({});
    setCrMessage('');
    setCrModal(true);
  };

  const handleSubmitChangeRequest = async () => {
    const proposed: Record<string, string | null> = {};
    Object.entries(crFields).forEach(([key, value]) => {
      const trimmed = value.trim();
      if (trimmed) proposed[key] = trimmed;
    });
    if (Object.keys(proposed).length === 0) {
      setFlash({ type: 'error', content: 'Enter at least one field to request a correction.' });
      return;
    }
    setSavingCr(true);
    try {
      await clientPortal.createChangeRequest(token, {
        proposed_changes: proposed,
        message: crMessage.trim() || undefined,
      });
      setFlash({ type: 'success', content: 'Change request submitted for review.' });
      setCrModal(false);
      const res = await clientPortal.listChangeRequests(token);
      setChangeRequests(res.data);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFlash({ type: 'error', content: detail || 'Failed to submit change request.' });
    } finally {
      setSavingCr(false);
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
          This portal link is invalid or has expired. Please contact your property manager for a new link.
        </Alert>
      </Box>
    );
  }

  return (
    <>
      {deleteModal}
      <ContentLayout
      header={
        <Header variant="h1" description={`${entityLabel(profile?.entity_type)} portal for ${profile?.name ?? '…'}`}>
          Client Portal
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
              id: 'overview',
              label: 'Overview',
              content: (
                <SpaceBetween size="l">
                  <Container header={<Header variant="h2">Portfolio at a glance</Header>}>
                    <ColumnLayout columns={4} variant="text-grid">
                      <div>
                        <Box variant="awsui-key-label">Offices</Box>
                        <Box variant="awsui-value-large">{summary?.office_count ?? 0}</Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Leases</Box>
                        <Box variant="awsui-value-large">{summary?.lease_count ?? 0}</Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Expiring within 180 days</Box>
                        <Box variant="awsui-value-large">{summary?.expiring_soon ?? 0}</Box>
                      </div>
                      <div>
                        <Box variant="awsui-key-label">Open work orders</Box>
                        <Box variant="awsui-value-large">{summary?.open_tickets ?? 0}</Box>
                      </div>
                    </ColumnLayout>
                  </Container>
                  {(summary?.expiring_soon ?? 0) > 0 && (
                    <Alert type="warning" header="Lease expirations approaching">
                      {summary?.expiring_soon} lease(s) expire within the next 180 days. See the
                      Leases tab for details.
                    </Alert>
                  )}
                </SpaceBetween>
              ),
            },
            {
              id: 'offices',
              label: `Offices (${offices.length})`,
              content: (
                <Table
                  items={offices}
                  empty={<Box textAlign="center" color="inherit">No offices on file.</Box>}
                  columnDefinitions={[
                    { id: 'number', header: '#', cell: (o: ClientPortalOffice) => o.office_number, width: 80 },
                    { id: 'name', header: 'Location', cell: (o: ClientPortalOffice) => o.location_name },
                    {
                      id: 'address',
                      header: 'Address',
                      cell: (o: ClientPortalOffice) =>
                        [o.address_line_1, o.city, o.state, o.zip_code].filter(Boolean).join(', ') || '—',
                    },
                    {
                      id: 'status',
                      header: 'Status',
                      cell: (o: ClientPortalOffice) => (
                        <Badge color={o.is_active ? 'green' : 'grey'}>{o.is_active ? 'Active' : 'Inactive'}</Badge>
                      ),
                      width: 110,
                    },
                    { id: 'leases', header: 'Leases', cell: (o: ClientPortalOffice) => o.lease_count, width: 90 },
                  ]}
                />
              ),
            },
            {
              id: 'leases',
              label: `Leases (${leases.length})`,
              content: (
                <Table
                  items={leases}
                  empty={<Box textAlign="center" color="inherit">No leases on file.</Box>}
                  columnDefinitions={[
                    { id: 'name', header: 'Lease', cell: (l: ClientPortalLease) => l.lease_name },
                    { id: 'office', header: 'Office', cell: (l: ClientPortalLease) => l.office_name || '—' },
                    {
                      id: 'commencement',
                      header: 'Commencement',
                      cell: (l: ClientPortalLease) =>
                        l.lease_commencement_date ? new Date(l.lease_commencement_date).toLocaleDateString() : '—',
                    },
                    {
                      id: 'expiration',
                      header: 'Expiration',
                      cell: (l: ClientPortalLease) =>
                        l.lease_expiration ? (
                          <SpaceBetween size="xs" direction="horizontal">
                            <span>{new Date(l.lease_expiration).toLocaleDateString()}</span>
                            {l.expiring_soon && <Badge color="red">Expiring soon</Badge>}
                          </SpaceBetween>
                        ) : '—',
                    },
                    {
                      id: 'notice',
                      header: 'Notice date',
                      cell: (l: ClientPortalLease) =>
                        l.lease_notice_date ? new Date(l.lease_notice_date).toLocaleDateString() : '—',
                    },
                  ]}
                />
              ),
            },
            {
              id: 'maintenance',
              label: `Maintenance (${tickets.length})`,
              content: (
                <Table
                  items={tickets}
                  empty={<Box textAlign="center" color="inherit">No work orders.</Box>}
                  columnDefinitions={[
                    { id: 'subject', header: 'Subject', cell: (t: ClientPortalTicket) => t.subject },
                    { id: 'office', header: 'Office', cell: (t: ClientPortalTicket) => t.office_name || '—' },
                    { id: 'priority', header: 'Priority', cell: (t: ClientPortalTicket) => t.priority },
                    {
                      id: 'status',
                      header: 'Status',
                      cell: (t: ClientPortalTicket) => (
                        <Badge color={t.status === 'closed' ? 'grey' : 'blue'}>{t.status}</Badge>
                      ),
                      width: 120,
                    },
                    {
                      id: 'created',
                      header: 'Created',
                      cell: (t: ClientPortalTicket) => new Date(t.created_at).toLocaleDateString(),
                      width: 140,
                    },
                  ]}
                />
              ),
            },
            {
              id: 'profile',
              label: 'Profile',
              content: profile ? (
                <SpaceBetween size="l">
                  <Container
                    header={
                      <Header
                        variant="h2"
                        description="This information is managed by your property manager. Spotted something out of date? Request a correction below."
                        actions={
                          <Button onClick={openChangeRequest}>Request a correction</Button>
                        }
                      >
                        Your Information
                      </Header>
                    }
                  >
                    <ColumnLayout columns={3} variant="text-grid">
                      {[
                        ['Name', profile.name],
                        ['Primary contact', profile.contact_name],
                        ['Email', profile.contact_email],
                        ['Phone', profile.contact_phone],
                        ['Address', profile.address],
                        ['Website', profile.website],
                      ].map(([label, value]) => (
                        <div key={label as string}>
                          <Box variant="awsui-key-label">{label}</Box>
                          <Box>{(value as string) || '—'}</Box>
                        </div>
                      ))}
                    </ColumnLayout>
                  </Container>
                  {changeRequests.length > 0 && (
                    <Table
                      items={changeRequests}
                      header={<Header variant="h2">Correction requests</Header>}
                      columnDefinitions={[
                        {
                          id: 'submitted',
                          header: 'Submitted',
                          cell: (r: ClientPortalChangeRequest) =>
                            new Date(r.created_at).toLocaleDateString(),
                          width: 140,
                        },
                        {
                          id: 'fields',
                          header: 'Requested changes',
                          cell: (r: ClientPortalChangeRequest) =>
                            summarizeChanges(r.proposed_changes),
                        },
                        {
                          id: 'status',
                          header: 'Status',
                          cell: (r: ClientPortalChangeRequest) => (
                            <Badge color={changeRequestStatusColor(r.status)}>{r.status}</Badge>
                          ),
                          width: 120,
                        },
                      ]}
                    />
                  )}
                </SpaceBetween>
              ) : null,
            },
            {
              id: 'contacts',
              label: `Contacts (${contacts.length})`,
              content: (
                <Table
                  items={contacts}
                  columnDefinitions={[
                    { id: 'name', header: 'Name', cell: (c: EntityContact) => c.contact_name },
                    { id: 'title', header: 'Title', cell: (c: EntityContact) => c.title || '—' },
                    { id: 'email', header: 'Email', cell: (c: EntityContact) => c.email || '—' },
                    { id: 'phone', header: 'Phone', cell: (c: EntityContact) => c.phone || c.mobile || '—' },
                    {
                      id: 'primary',
                      header: '',
                      cell: (c: EntityContact) => (c.is_primary ? <Badge color="blue">Primary</Badge> : null),
                      width: 90,
                    },
                    {
                      id: 'actions',
                      header: '',
                      cell: (c: EntityContact) => (
                        <SpaceBetween direction="horizontal" size="xs">
                          <Button variant="inline-link" onClick={() => openEditContact(c)}>Edit</Button>
                          <Button variant="inline-link" onClick={() => confirmDelete({ itemName: c.contact_name || 'this contact', description: <>Are you sure you want to remove <strong>{c.contact_name || 'this contact'}</strong>?</>, onConfirm: () => handleDeleteContact(c) })}>Remove</Button>
                        </SpaceBetween>
                      ),
                      width: 160,
                    },
                  ]}
                  empty={
                    <Box textAlign="center" padding="l">
                      <b>No additional contacts</b>
                      <Box color="text-body-secondary">Add the people we should reach out to.</Box>
                    </Box>
                  }
                  header={
                    <Header
                      description="Add or update your secondary contacts."
                      actions={<Button variant="primary" onClick={openCreateContact}>Add contact</Button>}
                    >
                      Secondary Contacts
                    </Header>
                  }
                />
              ),
            },
            {
              id: 'documents',
              label: `Documents (${documents.length})`,
              content: (
                <Container
                  header={
                    <Header
                      description="Upload documents to share with your property manager. You can remove documents you have uploaded."
                      actions={
                        <>
                          <input
                            ref={fileInputRef}
                            type="file"
                            style={{ display: 'none' }}
                            onChange={handleUpload}
                          />
                          <Button
                            variant="primary"
                            loading={uploading}
                            onClick={() => fileInputRef.current?.click()}
                          >
                            Upload document
                          </Button>
                        </>
                      }
                    >
                      Documents
                    </Header>
                  }
                >
                  <SpaceBetween size="m">
                    <div
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragActive(true);
                      }}
                      onDragLeave={() => setDragActive(false)}
                      onDrop={handleDrop}
                      style={{
                        border: `1px dashed ${dragActive ? '#0972d3' : '#b6bec9'}`,
                        borderRadius: 8,
                        padding: '16px',
                        textAlign: 'center',
                        background: dragActive ? '#f0f8ff' : 'transparent',
                      }}
                    >
                      <Box color="text-body-secondary">
                        Drag &amp; drop a file here, or use the Upload document button above.
                      </Box>
                    </div>
                    <Table
                      items={documents}
                      columnDefinitions={[
                        { id: 'name', header: 'File', cell: (d: Attachment) => d.original_filename },
                        { id: 'size', header: 'Size', cell: (d: Attachment) => formatBytes(d.file_size), width: 120 },
                        {
                          id: 'uploaded',
                          header: 'Uploaded',
                          cell: (d: Attachment) => new Date(d.created_at).toLocaleDateString(),
                          width: 160,
                        },
                        {
                          id: 'actions',
                          header: '',
                          cell: (d: Attachment) => (
                            <SpaceBetween direction="horizontal" size="xs">
                              <Button variant="inline-link" onClick={() => handleDownload(d)}>
                                Download
                              </Button>
                              {d.uploaded_by === 'client_portal' && (
                                <Button
                                  variant="inline-link"
                                  onClick={() =>
                                    confirmDelete({
                                      itemName: d.original_filename,
                                      description: (
                                        <>Are you sure you want to remove <strong>{d.original_filename}</strong>?</>
                                      ),
                                      onConfirm: () => handleDeleteDocument(d),
                                    })
                                  }
                                >
                                  Remove
                                </Button>
                              )}
                            </SpaceBetween>
                          ),
                          width: 200,
                        },
                      ]}
                      empty={
                        <Box textAlign="center" padding="l">
                          <b>No documents yet</b>
                          <Box color="text-body-secondary">Uploaded documents will appear here.</Box>
                        </Box>
                      }
                    />
                  </SpaceBetween>
                </Container>
              ),
            },
          ]}
        />
      </SpaceBetween>

      {/* ── Contact Modal ── */}
      <Modal
        visible={contactModal}
        onDismiss={() => setContactModal(false)}
        header={editingContact ? 'Edit contact' : 'Add contact'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setContactModal(false)}>Cancel</Button>
              <Button variant="primary" loading={savingContact} onClick={handleSaveContact}>Save</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Contact name" errorText={contactNameError}>
            <Input
              ref={contactNameRef}
              value={contactForm.contact_name}
              invalid={!!contactNameError}
              onChange={({ detail }) => {
                setContactForm((f) => ({ ...f, contact_name: detail.value }));
                if (contactNameError) setContactNameError('');
              }}
            />
          </FormField>
          <FormField label="Title">
            <Input
              value={contactForm.title}
              onChange={({ detail }) => setContactForm((f) => ({ ...f, title: detail.value }))}
            />
          </FormField>
          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Email">
              <Input
                value={contactForm.email}
                type="email"
                onChange={({ detail }) => setContactForm((f) => ({ ...f, email: detail.value }))}
              />
            </FormField>
            <FormField label="Phone">
              <Input
                value={contactForm.phone}
                onChange={({ detail }) => setContactForm((f) => ({ ...f, phone: detail.value }))}
              />
            </FormField>
            <FormField label="Mobile">
              <Input
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

      {/* ── Change-request Modal ── */}
      <Modal
        visible={crModal}
        onDismiss={() => setCrModal(false)}
        header="Request a correction"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setCrModal(false)}>Cancel</Button>
              <Button variant="primary" loading={savingCr} onClick={handleSubmitChangeRequest}>
                Submit request
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <Box color="text-body-secondary">
            Fill in only the fields you want corrected. Your property manager will review and apply
            approved changes.
          </Box>
          {CHANGE_REQUEST_FIELDS.map((f) => (
            <FormField key={f.key} label={f.label}>
              <Input
                value={crFields[f.key] ?? ''}
                onChange={({ detail }) =>
                  setCrFields((prev) => ({ ...prev, [f.key]: detail.value }))
                }
              />
            </FormField>
          ))}
          <FormField label="Note (optional)">
            <Textarea
              value={crMessage}
              onChange={({ detail }) => setCrMessage(detail.value)}
              rows={3}
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
    </>
  );
};

export default ClientPortalPage;
