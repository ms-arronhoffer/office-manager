import React, { useCallback, useEffect, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { leasing } from '@/api';
import type { Resident, ResidentStatus } from '@/types';

const RESIDENT_STATUSES: ResidentStatus[] = ['prospect', 'current', 'past'];

const residentBadge = (s: ResidentStatus) => {
  const color = s === 'current' ? 'green' : s === 'prospect' ? 'blue' : 'grey';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s}</Badge>;
};

interface Opt { label: string; value: string; }

const ResidentsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [residents, setResidents] = useState<Resident[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<Opt>({ label: 'All statuses', value: '' });

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Resident | null>(null);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [statusValue, setStatusValue] = useState<ResidentStatus>('prospect');
  const [emergencyName, setEmergencyName] = useState('');
  const [emergencyPhone, setEmergencyPhone] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);

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
    setStatusValue('prospect');
    setEmergencyName('');
    setEmergencyPhone('');
    setNotes('');
    setModalOpen(true);
  };

  const openEdit = (r: Resident) => {
    setEditing(r);
    setFirstName(r.first_name);
    setLastName(r.last_name);
    setEmail(r.email ?? '');
    setPhone(r.phone ?? '');
    setStatusValue(r.status);
    setEmergencyName(r.emergency_contact_name ?? '');
    setEmergencyPhone(r.emergency_contact_phone ?? '');
    setNotes(r.notes ?? '');
    setModalOpen(true);
  };

  const save = async () => {
    if (!firstName.trim() || !lastName.trim()) {
      addFlash({ type: 'error', content: 'First and last name are required.' });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim() || null,
        phone: phone.trim() || null,
        status: statusValue,
        emergency_contact_name: emergencyName.trim() || null,
        emergency_contact_phone: emergencyPhone.trim() || null,
        notes: notes.trim() || null,
      };
      if (editing) {
        await leasing.updateResident(editing.id, payload);
        addFlash({ type: 'success', content: 'Resident updated.' });
      } else {
        await leasing.createResident(payload);
        addFlash({ type: 'success', content: 'Resident created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save resident.' });
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

  return (
    <SpaceBetween size="l">
      <Table<Resident>
        loading={loading}
        items={residents}
        variant="container"
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
            cell: (r) => `${r.first_name} ${r.last_name}`,
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
                <Button variant="inline-link" onClick={() => remove(r)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No residents yet.</Box>}
      />

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editing ? 'Edit resident' : 'Add resident'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={saving} onClick={save}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <ColumnLayout columns={2}>
            <FormField label="First name">
              <Input value={firstName} onChange={({ detail }) => setFirstName(detail.value)} />
            </FormField>
            <FormField label="Last name">
              <Input value={lastName} onChange={({ detail }) => setLastName(detail.value)} />
            </FormField>
            <FormField label="Email">
              <Input value={email} onChange={({ detail }) => setEmail(detail.value)} />
            </FormField>
            <FormField label="Phone">
              <Input value={phone} onChange={({ detail }) => setPhone(detail.value)} />
            </FormField>
            <FormField label="Status">
              <Select
                selectedOption={{ label: statusValue, value: statusValue }}
                onChange={({ detail }) =>
                  setStatusValue(detail.selectedOption.value as ResidentStatus)
                }
                options={RESIDENT_STATUSES.map((s) => ({ label: s, value: s }))}
              />
            </FormField>
            <FormField label="Emergency contact">
              <Input
                value={emergencyName}
                onChange={({ detail }) => setEmergencyName(detail.value)}
              />
            </FormField>
            <FormField label="Emergency phone">
              <Input
                value={emergencyPhone}
                onChange={({ detail }) => setEmergencyPhone(detail.value)}
              />
            </FormField>
          </ColumnLayout>
          <FormField label="Notes">
            <Textarea value={notes} onChange={({ detail }) => setNotes(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default ResidentsPage;
