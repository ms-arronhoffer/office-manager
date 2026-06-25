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
import { landlords as landlordsApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import { formatAddress } from '@/components/common/AddressFields';
import type { Landlord, LandlordAdditionalName, LandlordContact } from '@/types';

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
  const [contactForm, setContactForm] = useState({ contact_name: '', title: '', email: '', phone: '', notes: '' });
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
      const label = landlord.name;
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
        email: contactForm.email.trim() || undefined,
        phone: contactForm.phone.trim() || undefined,
        notes: contactForm.notes.trim() || undefined,
      });
      setContactForm({ contact_name: '', title: '', email: '', phone: '', notes: '' });
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
              {landlord.name}
            </Header>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Landlord Information</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <ValuePair label="Name" value={landlord.contact_name} />
              <ValuePair label="Company" value={landlord.landlord_company} />
              <ValuePair label="Email" value={landlord.contact_email} />
              <ValuePair label="Phone" value={landlord.contact_phone} />
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
                          setContactForm({ contact_name: '', title: '', email: '', phone: '', notes: '' });
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
                  cell: (item) => item.name,
                },
                {
                  id: 'role',
                  header: 'Role',
                  cell: (item) => item.role || '—',
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
