import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import { listings, leasing } from '@/api';
import type { VacancyListing, ListingStatus, RentalUnit } from '@/types';

const fmtMoney = (v: string | null) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

interface Opt { label: string; value: string; }

const listingBadge = (s: ListingStatus) => {
  const color = s === 'published' ? 'green' : s === 'leased' ? 'grey' : 'blue';
  return <Badge color={color as 'green' | 'grey' | 'blue'}>{s}</Badge>;
};

const VacancyListingsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [items, setItems] = useState<VacancyListing[]>([]);
  const [units, setUnits] = useState<RentalUnit[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<VacancyListing | null>(null);
  const [unitId, setUnitId] = useState('');
  const [title, setTitle] = useState('');
  const [headline, setHeadline] = useState('');
  const [description, setDescription] = useState('');
  const [marketingRent, setMarketingRent] = useState('');
  const [availableDate, setAvailableDate] = useState('');
  const [amenities, setAmenities] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [l, u] = await Promise.all([listings.list(), leasing.listUnits()]);
      setItems(l.data);
      setUnits(u.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load listings.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const unitLabel = useCallback(
    (id: string) => {
      const u = units.find((x) => x.id === id);
      return u ? u.unit_number + (u.name ? ` · ${u.name}` : '') : id;
    },
    [units],
  );

  const unitOptions: Opt[] = useMemo(
    () => units.map((u) => ({ label: unitLabel(u.id), value: u.id })),
    [units, unitLabel],
  );

  const openCreate = () => {
    setEditing(null);
    setUnitId('');
    setTitle('');
    setHeadline('');
    setDescription('');
    setMarketingRent('');
    setAvailableDate('');
    setAmenities('');
    setContactEmail('');
    setModalOpen(true);
  };

  const openEdit = (l: VacancyListing) => {
    setEditing(l);
    setUnitId(l.unit_id);
    setTitle(l.title);
    setHeadline(l.headline ?? '');
    setDescription(l.description ?? '');
    setMarketingRent(l.marketing_rent ?? '');
    setAvailableDate(l.available_date ?? '');
    setAmenities((l.amenities ?? []).join(', '));
    setContactEmail(l.contact_email ?? '');
    setModalOpen(true);
  };

  const save = async () => {
    if (!editing && !unitId) {
      addFlash({ type: 'error', content: 'A unit is required.' });
      return;
    }
    if (!title.trim()) {
      addFlash({ type: 'error', content: 'Title is required.' });
      return;
    }
    setSaving(true);
    try {
      const amenityList = amenities
        .split(',')
        .map((a) => a.trim())
        .filter(Boolean);
      const common = {
        title: title.trim(),
        headline: headline.trim() || null,
        description: description.trim() || null,
        marketing_rent: marketingRent.trim() || null,
        available_date: availableDate || null,
        amenities: amenityList.length ? amenityList : null,
        contact_email: contactEmail.trim() || null,
      };
      if (editing) {
        await listings.update(editing.id, common);
        addFlash({ type: 'success', content: 'Listing updated.' });
      } else {
        await listings.create({ unit_id: unitId, ...common });
        addFlash({ type: 'success', content: 'Listing created.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save listing.' });
    } finally {
      setSaving(false);
    }
  };

  const doAction = async (
    l: VacancyListing,
    action: 'publish' | 'unpublish' | 'markLeased',
  ) => {
    try {
      await listings[action](l.id);
      addFlash({ type: 'success', content: 'Listing updated.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Action failed.' });
    }
  };

  const remove = async (l: VacancyListing) => {
    if (!window.confirm('Delete this listing?')) return;
    try {
      await listings.remove(l.id);
      addFlash({ type: 'success', content: 'Listing deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete listing.' });
    }
  };

  return (
    <SpaceBetween size="l">
      <Table<VacancyListing>
        loading={loading}
        items={items}
        variant="container"
        header={
          <Header
            counter={`(${items.length})`}
            actions={
              <Button variant="primary" onClick={openCreate}>
                Add listing
              </Button>
            }
          >
            Vacancy listings
          </Header>
        }
        columnDefinitions={[
          { id: 'title', header: 'Title', cell: (l) => l.title },
          { id: 'unit', header: 'Unit', cell: (l) => unitLabel(l.unit_id) },
          { id: 'rent', header: 'Rent', cell: (l) => fmtMoney(l.marketing_rent) },
          { id: 'available', header: 'Available', cell: (l) => l.available_date ?? '—' },
          { id: 'status', header: 'Status', cell: (l) => listingBadge(l.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (l) => (
              <SpaceBetween direction="horizontal" size="xs">
                {l.status === 'draft' && (
                  <Button variant="inline-link" onClick={() => doAction(l, 'publish')}>
                    Publish
                  </Button>
                )}
                {l.status === 'published' && (
                  <Button variant="inline-link" onClick={() => doAction(l, 'unpublish')}>
                    Unpublish
                  </Button>
                )}
                {l.status !== 'leased' && (
                  <Button variant="inline-link" onClick={() => doAction(l, 'markLeased')}>
                    Mark leased
                  </Button>
                )}
                <Button variant="inline-link" onClick={() => openEdit(l)}>
                  Edit
                </Button>
                <Button variant="inline-link" onClick={() => remove(l)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No listings yet.</Box>}
      />

      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editing ? 'Edit listing' : 'Add listing'}
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
          <FormField label="Unit">
            <Select
              disabled={!!editing}
              selectedOption={unitOptions.find((o) => o.value === unitId) ?? null}
              onChange={({ detail }) => setUnitId(detail.selectedOption.value ?? '')}
              options={unitOptions}
              filteringType="auto"
              placeholder="Select a unit"
            />
          </FormField>
          <FormField label="Title">
            <Input value={title} onChange={({ detail }) => setTitle(detail.value)} />
          </FormField>
          <FormField label="Headline">
            <Input value={headline} onChange={({ detail }) => setHeadline(detail.value)} />
          </FormField>
          <FormField label="Description">
            <Textarea
              value={description}
              onChange={({ detail }) => setDescription(detail.value)}
              rows={4}
            />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Marketing rent">
              <Input
                type="number"
                value={marketingRent}
                onChange={({ detail }) => setMarketingRent(detail.value)}
              />
            </FormField>
            <FormField label="Available date">
              <Input
                type="date"
                value={availableDate}
                onChange={({ detail }) => setAvailableDate(detail.value)}
              />
            </FormField>
          </ColumnLayout>
          <FormField label="Amenities (comma-separated)">
            <Input value={amenities} onChange={({ detail }) => setAmenities(detail.value)} />
          </FormField>
          <FormField label="Contact email">
            <Input value={contactEmail} onChange={({ detail }) => setContactEmail(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default VacancyListingsPage;
