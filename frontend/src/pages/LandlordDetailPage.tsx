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
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Checkbox from '@cloudscape-design/components/checkbox';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import { landlords as landlordsApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import { formatAddress } from '@/components/common/AddressFields';
import type { Landlord, LandlordAdditionalName, LandlordContact, LandlordOfficeRef } from '@/types';

const CONTACT_TYPE_OPTIONS = [
  { label: 'General', value: 'general' },
  { label: 'Billing', value: 'billing' },
  { label: 'Maintenance', value: 'maintenance' },
  { label: 'Property Manager', value: 'property_manager' },
  { label: 'Legal', value: 'legal' },
  { label: 'Emergency', value: 'emergency' },
];

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

  const [landlord, setLandlord] = useState<Landlord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Contact form state
  const [addContactVisible, setAddContactVisible] = useState(false);
  const [contactForm, setContactForm] = useState({ contact_name: '', title: '', contact_type: '', is_primary: false, email: '', phone: '', notes: '' });
  const [addingContact, setAddingContact] = useState(false);
  const [contactError, setContactError] = useState<string | null>(null);
  const [deletingContactId, setDeletingContactId] = useState<string | null>(null);

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

  const handleAddContact = async () => {
    if (!id || !contactForm.contact_name.trim()) return;
    setAddingContact(true);
    setContactError(null);
    try {
      await landlordsApi.addContact(id, {
        contact_name: contactForm.contact_name.trim(),
        title: contactForm.title.trim() || undefined,
        contact_type: contactForm.contact_type || undefined,
        is_primary: contactForm.is_primary,
        email: contactForm.email.trim() || undefined,
        phone: contactForm.phone.trim() || undefined,
        notes: contactForm.notes.trim() || undefined,
      });
      setContactForm({ contact_name: '', title: '', contact_type: '', is_primary: false, email: '', phone: '', notes: '' });
      setAddContactVisible(false);
      await fetchLandlord();
    } catch {
      setContactError('Failed to add contact.');
    } finally {
      setAddingContact(false);
    }
  };

  const handleDeleteContact = async (contactId: string) => {
    if (!id) return;
    setDeletingContactId(contactId);
    setContactError(null);
    try {
      await landlordsApi.deleteContact(id, contactId);
      await fetchLandlord();
    } catch {
      setContactError('Failed to delete contact.');
    } finally {
      setDeletingContactId(null);
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
                  <Button variant="normal" onClick={handleDelete}>
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
              <ValuePair label="Management Company" value={landlord.management_company} />
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

          {/* Owned Offices */}
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
          <Container
            header={
              <Header
                variant="h2"
                counter={`(${(landlord.contacts ?? []).length})`}
                actions={
                  canEdit ? (
                    <Button onClick={() => setAddContactVisible(true)}>Add Contact</Button>
                  ) : undefined
                }
              >
                Additional Contacts
              </Header>
            }
          >
            <SpaceBetween size="m">
              {contactError && (
                <Alert type="error" dismissible onDismiss={() => setContactError(null)}>
                  {contactError}
                </Alert>
              )}

              <Table<LandlordContact>
                columnDefinitions={[
                  { id: 'name', header: 'Name', cell: (item) => item.contact_name },
                  {
                    id: 'type',
                    header: 'Type',
                    cell: (item) =>
                      item.contact_type
                        ? item.contact_type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
                        : '—',
                  },
                  {
                    id: 'primary',
                    header: 'Primary',
                    cell: (item) =>
                      item.is_primary ? (
                        <StatusIndicator type="success">Primary</StatusIndicator>
                      ) : (
                        '—'
                      ),
                  },
                  { id: 'title', header: 'Title', cell: (item) => item.title || '—' },
                  { id: 'email', header: 'Email', cell: (item) => item.email || '—' },
                  { id: 'phone', header: 'Phone', cell: (item) => item.phone || '—' },
                  { id: 'notes', header: 'Notes', cell: (item) => item.notes || '—' },
                  ...(canEdit
                    ? [
                        {
                          id: 'actions',
                          header: '',
                          cell: (item: LandlordContact) => (
                            <Button
                              variant="inline-icon"
                              iconName="remove"
                              ariaLabel="Delete contact"
                              loading={deletingContactId === item.id}
                              onClick={() => handleDeleteContact(item.id)}
                            />
                          ),
                          width: 50,
                        },
                      ]
                    : []),
                ]}
                items={landlord.contacts ?? []}
                empty={
                  <Box textAlign="center" color="inherit" padding="m">
                    No additional contacts.
                  </Box>
                }
              />

              {addContactVisible && (
                <Container header={<Header variant="h3">New Contact</Header>}>
                  <SpaceBetween size="s">
                    <FormField label="Name" constraintText="Required">
                      <Input
                        value={contactForm.contact_name}
                        onChange={({ detail }) =>
                          setContactForm((f) => ({ ...f, contact_name: detail.value }))
                        }
                        placeholder="Contact name"
                      />
                    </FormField>
                    <FormField label="Title">
                      <Input
                        value={contactForm.title}
                        onChange={({ detail }) =>
                          setContactForm((f) => ({ ...f, title: detail.value }))
                        }
                        placeholder="e.g., Property Manager"
                      />
                    </FormField>
                    <FormField label="Contact Type">
                      <Select
                        selectedOption={
                          contactForm.contact_type
                            ? CONTACT_TYPE_OPTIONS.find((o) => o.value === contactForm.contact_type) ?? null
                            : null
                        }
                        onChange={({ detail }) =>
                          setContactForm((f) => ({ ...f, contact_type: detail.selectedOption.value ?? '' }))
                        }
                        options={CONTACT_TYPE_OPTIONS}
                        placeholder="Select a type"
                      />
                    </FormField>
                    <Checkbox
                      checked={contactForm.is_primary}
                      onChange={({ detail }) =>
                        setContactForm((f) => ({ ...f, is_primary: detail.checked }))
                      }
                    >
                      Primary contact
                    </Checkbox>
                    <FormField label="Email">
                      <Input
                        value={contactForm.email}
                        onChange={({ detail }) =>
                          setContactForm((f) => ({ ...f, email: detail.value }))
                        }
                        placeholder="Email address"
                        type="email"
                      />
                    </FormField>
                    <FormField label="Phone">
                      <Input
                        value={contactForm.phone}
                        onChange={({ detail }) =>
                          setContactForm((f) => ({ ...f, phone: detail.value }))
                        }
                        placeholder="Phone number"
                      />
                    </FormField>
                    <FormField label="Notes">
                      <Input
                        value={contactForm.notes}
                        onChange={({ detail }) =>
                          setContactForm((f) => ({ ...f, notes: detail.value }))
                        }
                        placeholder="Additional info"
                      />
                    </FormField>
                    <SpaceBetween direction="horizontal" size="xs">
                      <Button
                        onClick={() => {
                          setAddContactVisible(false);
                          setContactForm({ contact_name: '', title: '', contact_type: '', is_primary: false, email: '', phone: '', notes: '' });
                        }}
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="primary"
                        onClick={handleAddContact}
                        loading={addingContact}
                        disabled={!contactForm.contact_name.trim()}
                      >
                        Add Contact
                      </Button>
                    </SpaceBetween>
                  </SpaceBetween>
                </Container>
              )}
            </SpaceBetween>
          </Container>

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
