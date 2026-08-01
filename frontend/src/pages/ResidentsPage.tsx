import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Link from '@cloudscape-design/components/link';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { useAuth } from '@/auth/AuthContext';
import { leasing, attachments as attachmentsApi } from '@/api';
import useListCollection from '@/hooks/useListCollection';
import { exportRowsToCsv } from '@/lib/csv';
import type { CsvColumn } from '@/lib/csv';
import PortalInviteButton from '@/components/common/PortalInviteButton';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import EntityFormModal from '@/components/common/EntityFormModal';
import CreateWizardModal from '@/components/common/CreateWizardModal';
import FileUploadField, { type QueuedFile } from '@/components/common/FileUploadField';
import type { Resident, ResidentStatus } from '@/types';

const RESIDENT_STATUSES: ResidentStatus[] = ['prospect', 'current', 'past'];

const RESIDENT_CSV_COLUMNS: CsvColumn<Resident>[] = [
  { header: 'First name', value: (r) => r.first_name },
  { header: 'Last name', value: (r) => r.last_name },
  { header: 'Email', value: (r) => r.email },
  { header: 'Phone', value: (r) => r.phone },
  { header: 'Status', value: (r) => r.status },
];

const residentBadge = (s: ResidentStatus) => {
  const color = s === 'current' ? 'green' : s === 'prospect' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

interface Opt { label: string; value: string; }

const ResidentsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const canEditDocuments = user?.role === 'admin' || user?.role === 'editor';
  const [residents, setResidents] = useState<Resident[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<Opt>({ label: 'All statuses', value: '' });

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Resident | null>(null);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [alternatePhone, setAlternatePhone] = useState('');
  const [company, setCompany] = useState('');
  const [addr1, setAddr1] = useState('');
  const [addr2, setAddr2] = useState('');
  const [city, setCity] = useState('');
  const [stateVal, setStateVal] = useState('');
  const [zip, setZip] = useState('');
  const [statusValue, setStatusValue] = useState<ResidentStatus>('prospect');
  const [emergencyName, setEmergencyName] = useState('');
  const [emergencyPhone, setEmergencyPhone] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queuedFiles, setQueuedFiles] = useState<QueuedFile[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = statusFilter.value ? { status: statusFilter.value } : undefined;
      const r = await leasing.listResidents(params);
      setResidents(r.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load residents.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash, statusFilter.value]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setFirstName('');
    setLastName('');
    setEmail('');
    setPhone('');
    setAlternatePhone('');
    setCompany('');
    setAddr1('');
    setAddr2('');
    setCity('');
    setStateVal('');
    setZip('');
    setStatusValue('prospect');
    setEmergencyName('');
    setEmergencyPhone('');
    setNotes('');
    setError(null);
    setQueuedFiles([]);
    setModalOpen(true);
  };

  const openEdit = (r: Resident) => {
    setEditing(r);
    setFirstName(r.first_name);
    setLastName(r.last_name);
    setEmail(r.email ?? '');
    setPhone(r.phone ?? '');
    setAlternatePhone(r.alternate_phone ?? '');
    setCompany(r.company ?? '');
    setAddr1(r.address_line_1 ?? '');
    setAddr2(r.address_line_2 ?? '');
    setCity(r.city ?? '');
    setStateVal(r.state ?? '');
    setZip(r.zip_code ?? '');
    setStatusValue(r.status);
    setEmergencyName(r.emergency_contact_name ?? '');
    setEmergencyPhone(r.emergency_contact_phone ?? '');
    setNotes(r.notes ?? '');
    setError(null);
    setQueuedFiles([]);
    setModalOpen(true);
  };

  // Lets the resident master record hand editing back to this list via ?edit=<id>.
  useEffect(() => {
    const editId = searchParams.get('edit');
    if (!editId || loading) return;
    const match = residents.find((r) => r.id === editId);
    if (match) {
      openEdit(match);
      searchParams.delete('edit');
      setSearchParams(searchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, residents, loading]);

  const save = async () => {
    if (!firstName.trim() || !lastName.trim()) {
      setError('First and last name are required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim() || null,
        phone: phone.trim() || null,
        alternate_phone: alternatePhone.trim() || null,
        company: company.trim() || null,
        address_line_1: addr1.trim() || null,
        address_line_2: addr2.trim() || null,
        city: city.trim() || null,
        state: stateVal.trim() || null,
        zip_code: zip.trim() || null,
        status: statusValue,
        emergency_contact_name: emergencyName.trim() || null,
        emergency_contact_phone: emergencyPhone.trim() || null,
        notes: notes.trim() || null,
      };
      if (editing) {
        await leasing.updateResident(editing.id, payload);
        addFlash({ type: 'success', content: 'Resident updated.' });
      } else {
        const res = await leasing.createResident(payload);
        const newId = String(res.data.id);
        const failed: string[] = [];
        for (const qf of queuedFiles) {
          try {
            await attachmentsApi.upload('resident', newId, qf.file);
          } catch {
            failed.push(qf.file.name);
          }
        }
        if (failed.length > 0) {
          addFlash({
            type: 'warning',
            content: `Resident created, but ${failed.length} attachment(s) failed: ${failed.join(', ')}.`,
          });
        } else {
          addFlash({ type: 'success', content: 'Resident created.' });
        }
      }
      setModalOpen(false);
      await load();
    } catch {
      setError('Failed to save resident.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (r: Resident) => {
    if (!window.confirm(`Delete ${r.first_name} ${r.last_name}?`)) return;
    try {
      await leasing.deleteResident(r.id);
      addFlash({ type: 'success', content: 'Resident deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete resident.' });
    }
  };

  const collection = useListCollection(residents, {
    entity: 'residents',
    filterPlaceholder: 'Search residents',
    searchText: (r) =>
      [r.first_name, r.last_name, r.email, r.phone, r.company, r.status]
        .filter(Boolean)
        .join(' '),
    empty: (
      <Box textAlign="center" padding="m">
        <SpaceBetween size="xs">
          <Box>No residents yet.</Box>
          <Button onClick={openCreate}>Add your first resident</Button>
        </SpaceBetween>
      </Box>
    ),
  });

  const identityFields = (
    <ColumnLayout columns={2}>
      <FormField label="First name">
        <Input value={firstName} onChange={({ detail }) => setFirstName(detail.value)} />
      </FormField>
      <FormField label="Last name">
        <Input value={lastName} onChange={({ detail }) => setLastName(detail.value)} />
      </FormField>
      <FormField label="Status">
        <Select
          selectedOption={{ label: statusValue, value: statusValue }}
          onChange={({ detail }) => setStatusValue(detail.selectedOption.value as ResidentStatus)}
          options={RESIDENT_STATUSES.map((s) => ({ label: s, value: s }))}
        />
      </FormField>
      <FormField label="Company">
        <Input value={company} onChange={({ detail }) => setCompany(detail.value)} />
      </FormField>
    </ColumnLayout>
  );

  const contactFields = (
    <ColumnLayout columns={2}>
      <FormField label="Email">
        <Input value={email} onChange={({ detail }) => setEmail(detail.value)} />
      </FormField>
      <FormField label="Phone">
        <Input value={phone} onChange={({ detail }) => setPhone(detail.value)} />
      </FormField>
      <FormField label="Alternate phone">
        <Input value={alternatePhone} onChange={({ detail }) => setAlternatePhone(detail.value)} />
      </FormField>
    </ColumnLayout>
  );

  const addressFields = (
    <ColumnLayout columns={2}>
      <FormField label="Address line 1">
        <Input value={addr1} onChange={({ detail }) => setAddr1(detail.value)} />
      </FormField>
      <FormField label="Address line 2">
        <Input value={addr2} onChange={({ detail }) => setAddr2(detail.value)} />
      </FormField>
      <FormField label="City">
        <Input value={city} onChange={({ detail }) => setCity(detail.value)} />
      </FormField>
      <FormField label="State">
        <Input value={stateVal} onChange={({ detail }) => setStateVal(detail.value)} />
      </FormField>
      <FormField label="ZIP code">
        <Input value={zip} onChange={({ detail }) => setZip(detail.value)} />
      </FormField>
    </ColumnLayout>
  );

  const emergencyFields = (
    <SpaceBetween size="m">
      <ColumnLayout columns={2}>
        <FormField label="Emergency contact">
          <Input value={emergencyName} onChange={({ detail }) => setEmergencyName(detail.value)} />
        </FormField>
        <FormField label="Emergency phone">
          <Input value={emergencyPhone} onChange={({ detail }) => setEmergencyPhone(detail.value)} />
        </FormField>
      </ColumnLayout>
      <FormField label="Notes">
        <Textarea value={notes} onChange={({ detail }) => setNotes(detail.value)} />
      </FormField>
    </SpaceBetween>
  );

  const createDirty = Boolean(
    firstName || lastName || email || phone || company || addr1 || notes || queuedFiles.length,
  );

  return (
    <SpaceBetween size="l">
      <Table<Resident>
        {...collection.collectionProps}
        loading={loading}
        items={collection.items}
        variant="container"
        selectionType="multi"
        filter={collection.filter}
        pagination={collection.pagination}
        header={
          <Header
            counter={`(${residents.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Select
                  selectedOption={statusFilter}
                  onChange={({ detail }) => setStatusFilter(detail.selectedOption as Opt)}
                  options={[
                    { label: 'All statuses', value: '' },
                    ...RESIDENT_STATUSES.map((s) => ({ label: s, value: s })),
                  ]}
                />
                <Button
                  disabled={collection.selectedItems.length === 0}
                  onClick={() =>
                    exportRowsToCsv('residents.csv', RESIDENT_CSV_COLUMNS, collection.selectedItems)
                  }
                >
                  Export selected
                </Button>
                <Button variant="primary" onClick={openCreate}>
                  Add resident
                </Button>
              </SpaceBetween>
            }
          >
            Residents
          </Header>
        }
        columnDefinitions={[
          {
            id: 'name',
            header: 'Name',
            cell: (r) => (
              <Link
                onFollow={(e) => {
                  e.preventDefault();
                  navigate(`/residential/residents/${r.id}`);
                }}
                href={`/residential/residents/${r.id}`}
              >
                {`${r.first_name} ${r.last_name}`}
              </Link>
            ),
          },
          { id: 'email', header: 'Email', cell: (r) => r.email ?? '—' },
          { id: 'phone', header: 'Phone', cell: (r) => r.phone ?? '—' },
          { id: 'status', header: 'Status', cell: (r) => residentBadge(r.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (r) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => openEdit(r)}>
                  Edit
                </Button>
                <PortalInviteButton
                  entityLabel="resident"
                  entityName={`${r.first_name} ${r.last_name}`}
                  onInvite={() => leasing.inviteToPortal(r.id)}
                />
                <Button variant="inline-link" onClick={() => remove(r)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
      />

      <CreateWizardModal
        visible={modalOpen && !editing}
        entityLabel="resident"
        onCancel={() => setModalOpen(false)}
        onSubmit={save}
        submitting={saving}
        error={error}
        dirty={createDirty}
        onBulkComplete={load}
        bulk={{
          columns: [
            { key: 'first_name', label: 'First name', required: true },
            { key: 'last_name', label: 'Last name', required: true },
            { key: 'email', label: 'Email' },
            { key: 'phone', label: 'Phone' },
            { key: 'status', label: 'Status' },
          ],
          onSubmitRow: async (row) => {
            const status = RESIDENT_STATUSES.includes(row.status as ResidentStatus)
              ? (row.status as ResidentStatus)
              : 'prospect';
            await leasing.createResident({
              first_name: row.first_name.trim(),
              last_name: row.last_name.trim(),
              email: row.email?.trim() || null,
              phone: row.phone?.trim() || null,
              status,
            });
          },
        }}
        steps={[
          {
            title: 'Identity',
            description: 'Who is this resident?',
            content: identityFields,
            validate: () =>
              !firstName.trim() || !lastName.trim()
                ? 'First and last name are required.'
                : null,
          },
          { title: 'Contact', description: 'How do you reach them?', content: contactFields },
          { title: 'Address', description: 'Where do they receive mail?', content: addressFields },
          {
            title: 'Emergency & notes',
            description: 'Anything else worth recording.',
            content: (
              <SpaceBetween size="m">
                {emergencyFields}
                <FileUploadField files={queuedFiles} onChange={setQueuedFiles} disabled={saving} />
              </SpaceBetween>
            ),
          },
        ]}
      />

      <EntityFormModal
        visible={modalOpen && Boolean(editing)}
        onCancel={() => setModalOpen(false)}
        title="Edit resident"
        size="large"
        onSubmit={save}
        submitting={saving}
        error={error}
      >
        <SpaceBetween size="m">
          {identityFields}
          {contactFields}
          {addressFields}
          {emergencyFields}
          {editing && (
            <AttachmentsPanel
              entityType="resident"
              entityId={editing.id}
              canEdit={canEditDocuments}
            />
          )}
        </SpaceBetween>
      </EntityFormModal>
    </SpaceBetween>
  );
};

export default ResidentsPage;
