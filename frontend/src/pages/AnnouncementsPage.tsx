import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import EntityFormModal from '@/components/common/EntityFormModal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Multiselect from '@cloudscape-design/components/multiselect';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import { useFlashbar } from '@/context/FlashbarContext';
import { announcements as annApi, offices as officesApi } from '@/api';
import type {
  Announcement,
  AnnouncementChannel,
  ResidentStatus,
  Office,
} from '@/types';

interface Opt { label: string; value: string; }

const CHANNELS: AnnouncementChannel[] = ['portal', 'email', 'sms'];
const RESIDENT_STATUSES: ResidentStatus[] = ['prospect', 'current', 'past'];

const statusBadge = (s: string) => {
  const color = s === 'sent' ? 'green' : 'grey';
  return <Badge color={color as 'green' | 'grey'}>{s}</Badge>;
};

const AnnouncementsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [items, setItems] = useState<Announcement[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Announcement | null>(null);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [channels, setChannels] = useState<readonly Opt[]>([{ label: 'portal', value: 'portal' }]);
  const [audienceOffice, setAudienceOffice] = useState('');
  const [audienceStatus, setAudienceStatus] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await annApi.list();
      setItems(r.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load announcements.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    officesApi
      .list({ page_size: 200 })
      .then((r) => setOffices(r.data.items))
      .catch(() => undefined);
  }, []);

  const officeOptions: Opt[] = useMemo(
    () => [
      { label: 'All properties', value: '' },
      ...offices.map((o) => ({
        label: `${o.office_number} · ${o.location_name}`,
        value: o.id,
      })),
    ],
    [offices],
  );

  const openCreate = () => {
    setEditing(null);
    setTitle('');
    setBody('');
    setChannels([{ label: 'portal', value: 'portal' }]);
    setAudienceOffice('');
    setAudienceStatus('');
    setModalOpen(true);
  };

  const openEdit = (a: Announcement) => {
    setEditing(a);
    setTitle(a.title);
    setBody(a.body);
    setChannels(a.channels.map((c) => ({ label: c, value: c })));
    setAudienceOffice(a.audience_office_id ?? '');
    setAudienceStatus(a.audience_resident_status ?? '');
    setModalOpen(true);
  };

  const save = async () => {
    if (!title.trim() || !body.trim()) {
      addFlash({ type: 'error', content: 'Title and body are required.' });
      return;
    }
    if (channels.length === 0) {
      addFlash({ type: 'error', content: 'Select at least one channel.' });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        title: title.trim(),
        body: body.trim(),
        channels: channels.map((c) => c.value as AnnouncementChannel),
        audience_office_id: audienceOffice || null,
        audience_resident_status: (audienceStatus || null) as ResidentStatus | null,
      };
      if (editing) {
        await annApi.update(editing.id, payload);
        addFlash({ type: 'success', content: 'Announcement updated.' });
      } else {
        await annApi.create(payload);
        addFlash({ type: 'success', content: 'Announcement created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save announcement.' });
    } finally {
      setSaving(false);
    }
  };

  const send = async (a: Announcement) => {
    if (!window.confirm('Send this announcement now?')) return;
    try {
      const r = await annApi.send(a.id);
      addFlash({
        type: 'success',
        content: `Sent to ${r.data.recipients} recipient(s) (${r.data.emailed} emailed, ${r.data.texted} texted).`,
      });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to send announcement.' });
    }
  };

  const remove = async (a: Announcement) => {
    if (!window.confirm('Delete this announcement?')) return;
    try {
      await annApi.remove(a.id);
      addFlash({ type: 'success', content: 'Announcement deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete announcement.' });
    }
  };

  return (
    <SpaceBetween size="l">
      <Table<Announcement>
        loading={loading}
        items={items}
        variant="container"
        header={
          <Header
            counter={`(${items.length})`}
            actions={
              <Button variant="primary" onClick={openCreate}>
                New announcement
              </Button>
            }
          >
            Announcements
          </Header>
        }
        columnDefinitions={[
          { id: 'title', header: 'Title', cell: (a) => a.title },
          { id: 'channels', header: 'Channels', cell: (a) => a.channels.join(', ') },
          { id: 'status', header: 'Status', cell: (a) => statusBadge(a.status) },
          { id: 'recipients', header: 'Recipients', cell: (a) => a.recipient_count },
          { id: 'sent', header: 'Sent at', cell: (a) => (a.sent_at ? a.sent_at.slice(0, 10) : '—') },
          {
            id: 'actions',
            header: 'Actions',
            cell: (a) => (
              <SpaceBetween direction="horizontal" size="xs">
                {a.status !== 'sent' && (
                  <>
                    <Button variant="inline-link" onClick={() => send(a)}>
                      Send
                    </Button>
                    <Button variant="inline-link" onClick={() => openEdit(a)}>
                      Edit
                    </Button>
                  </>
                )}
                <Button variant="inline-link" onClick={() => remove(a)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No announcements yet.</Box>}
      />

      <EntityFormModal
        visible={modalOpen}
        onCancel={() => setModalOpen(false)}
        title={editing ? 'Edit announcement' : 'New announcement'}
        submitLabel="Save"
        submitting={saving}
        onSubmit={save}
      >
        <SpaceBetween size="m">
          <FormField label="Title">
            <Input value={title} onChange={({ detail }) => setTitle(detail.value)} />
          </FormField>
          <FormField label="Body">
            <Textarea value={body} onChange={({ detail }) => setBody(detail.value)} rows={5} />
          </FormField>
          <FormField label="Channels">
            <Multiselect
              selectedOptions={channels}
              onChange={({ detail }) => setChannels(detail.selectedOptions as Opt[])}
              options={CHANNELS.map((c) => ({ label: c, value: c }))}
            />
          </FormField>
          <FormField label="Audience — property">
            <Select
              selectedOption={officeOptions.find((o) => o.value === audienceOffice) ?? officeOptions[0]}
              onChange={({ detail }) => setAudienceOffice(detail.selectedOption.value ?? '')}
              options={officeOptions}
              filteringType="auto"
            />
          </FormField>
          <FormField label="Audience — resident status">
            <Select
              selectedOption={{
                label: audienceStatus || 'All residents',
                value: audienceStatus,
              }}
              onChange={({ detail }) => setAudienceStatus(detail.selectedOption.value ?? '')}
              options={[
                { label: 'All residents', value: '' },
                ...RESIDENT_STATUSES.map((s) => ({ label: s, value: s })),
              ]}
            />
          </FormField>
        </SpaceBetween>
      </EntityFormModal>
    </SpaceBetween>
  );
};

export default AnnouncementsPage;
