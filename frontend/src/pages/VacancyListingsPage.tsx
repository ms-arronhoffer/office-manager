import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import EntityFormModal from '@/components/common/EntityFormModal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Checkbox from '@cloudscape-design/components/checkbox';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { useAuth } from '@/auth/AuthContext';
import { copyToClipboard } from '@/utils/clipboard';
import { listings, leasing } from '@/api';
import type {
  VacancyListing,
  ListingStatus,
  RentalUnit,
  ListingPortal,
  ListingSyndication,
  KnownPortal,
} from '@/types';

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
  const { user } = useAuth();
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

  // Portal syndication state.
  const [portals, setPortals] = useState<ListingPortal[]>([]);
  const [portalsModalOpen, setPortalsModalOpen] = useState(false);
  const [catalog, setCatalog] = useState<KnownPortal[]>([]);
  const [customName, setCustomName] = useState('');
  const [customUrl, setCustomUrl] = useState('');
  const [syndicateModalOpen, setSyndicateModalOpen] = useState(false);
  const [syndicateListing, setSyndicateListing] = useState<VacancyListing | null>(null);
  const [selectedPortalIds, setSelectedPortalIds] = useState<string[]>([]);
  const [syndications, setSyndications] = useState<ListingSyndication[]>([]);
  const [syndicating, setSyndicating] = useState(false);

  const loadPortals = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([listings.listPortals(), listings.portalCatalog()]);
      setPortals(p.data);
      setCatalog(c.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load portals.' });
    }
  }, [addFlash]);

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
    loadPortals();
  }, [load, loadPortals]);

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

  // ── Portal management ───────────────────────────────────────────────────────

  const enableKnownPortal = async (p: KnownPortal) => {
    try {
      await listings.createPortal({
        name: p.name,
        slug: p.slug,
        website_url: p.website_url,
        delivery_mode: p.delivery_mode,
      });
      addFlash({ type: 'success', content: `${p.name} added.` });
      await loadPortals();
    } catch {
      addFlash({ type: 'error', content: 'Failed to add portal.' });
    }
  };

  const addCustomPortal = async () => {
    if (!customName.trim()) {
      addFlash({ type: 'error', content: 'Portal name is required.' });
      return;
    }
    try {
      await listings.createPortal({
        name: customName.trim(),
        slug: 'custom',
        website_url: customUrl.trim() || null,
        endpoint_url: customUrl.trim() || null,
        delivery_mode: customUrl.trim() ? 'webhook' : 'feed',
      });
      setCustomName('');
      setCustomUrl('');
      addFlash({ type: 'success', content: 'Custom portal added.' });
      await loadPortals();
    } catch {
      addFlash({ type: 'error', content: 'Failed to add custom portal.' });
    }
  };

  const togglePortalEnabled = async (p: ListingPortal) => {
    try {
      await listings.updatePortal(p.id, { is_enabled: !p.is_enabled });
      await loadPortals();
    } catch {
      addFlash({ type: 'error', content: 'Failed to update portal.' });
    }
  };

  const removePortal = async (p: ListingPortal) => {
    if (!window.confirm(`Remove portal "${p.name}"?`)) return;
    try {
      await listings.removePortal(p.id);
      await loadPortals();
    } catch {
      addFlash({ type: 'error', content: 'Failed to remove portal.' });
    }
  };

  // ── Syndication ─────────────────────────────────────────────────────────────

  const openSyndicate = async (l: VacancyListing) => {
    setSyndicateListing(l);
    setSelectedPortalIds([]);
    setSyndications([]);
    setSyndicateModalOpen(true);
    try {
      const { data } = await listings.listSyndications(l.id);
      setSyndications(data);
    } catch {
      /* non-fatal: modal still usable for a first-time post */
    }
  };

  const runSyndication = async () => {
    if (!syndicateListing || selectedPortalIds.length === 0) {
      addFlash({ type: 'error', content: 'Select at least one portal.' });
      return;
    }
    setSyndicating(true);
    try {
      const { data } = await listings.syndicate(syndicateListing.id, selectedPortalIds);
      setSyndications(data);
      setSelectedPortalIds([]);
      addFlash({ type: 'success', content: 'Listing posted to selected portals.' });
    } catch {
      addFlash({ type: 'error', content: 'Syndication failed.' });
    } finally {
      setSyndicating(false);
    }
  };

  const syndicationFor = (portalId: string) =>
    syndications.find((s) => s.portal_id === portalId);

  const enabledPortals = useMemo(() => portals.filter((p) => p.is_enabled), [portals]);
  const availableCatalog = useMemo(
    () => catalog.filter((c) => !portals.some((p) => p.slug === c.slug)),
    [catalog, portals],
  );

  // ── Syndication feed URLs (read-only, admin/super-admin only) ────────────────
  const canSeeFeed = user?.role === 'admin' || user?.is_super_admin === true;
  const organizationId = user?.organization_id;
  const feedUrls = useMemo(() => {
    if (!organizationId) return null;
    const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1';
    const absoluteBase = apiBase.startsWith('http')
      ? apiBase
      : `${window.location.origin}${apiBase}`;
    return {
      json: `${absoluteBase}/listings/feed/${organizationId}`,
      xml: `${absoluteBase}/listings/feed/${organizationId}.xml`,
    };
  }, [organizationId]);

  const copyFeedUrl = async (url: string) => {
    const ok = await copyToClipboard(url);
    addFlash({
      type: ok ? 'success' : 'error',
      content: ok
        ? 'Feed URL copied to clipboard.'
        : 'Could not copy automatically. Select the URL and copy it manually.',
    });
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
              <SpaceBetween direction="horizontal" size="xs">
                <Button iconName="share" onClick={() => setPortalsModalOpen(true)}>
                  Manage portals
                </Button>
                <Button variant="primary" onClick={openCreate}>
                  Add listing
                </Button>
              </SpaceBetween>
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
                {l.status === 'published' && (
                  <Button variant="inline-link" onClick={() => openSyndicate(l)}>
                    Syndicate
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

      <EntityFormModal
        visible={modalOpen}
        onCancel={() => setModalOpen(false)}
        title={editing ? 'Edit listing' : 'Add listing'}
        size="large"
        submitLabel="Save"
        submitting={saving}
        onSubmit={save}
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
      </EntityFormModal>

      {/* ── Manage portals ─────────────────────────────────────────────── */}
      <Modal
        visible={portalsModalOpen}
        onDismiss={() => setPortalsModalOpen(false)}
        size="large"
        header="Listing portals"
        footer={
          <Box float="right">
            <Button variant="primary" onClick={() => setPortalsModalOpen(false)}>
              Done
            </Button>
          </Box>
        }
      >
        <SpaceBetween size="l">
          <Table<ListingPortal>
            variant="embedded"
            items={portals}
            header={<Header>Configured portals</Header>}
            columnDefinitions={[
              { id: 'name', header: 'Portal', cell: (p) => p.name },
              { id: 'mode', header: 'Delivery', cell: (p) => p.delivery_mode },
              {
                id: 'enabled',
                header: 'Enabled',
                cell: (p) =>
                  p.is_enabled ? (
                    <Badge color="green">enabled</Badge>
                  ) : (
                    <Badge color="grey">disabled</Badge>
                  ),
              },
              {
                id: 'actions',
                header: 'Actions',
                cell: (p) => (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button variant="inline-link" onClick={() => togglePortalEnabled(p)}>
                      {p.is_enabled ? 'Disable' : 'Enable'}
                    </Button>
                    <Button variant="inline-link" onClick={() => removePortal(p)}>
                      Remove
                    </Button>
                  </SpaceBetween>
                ),
              },
            ]}
            empty={<Box textAlign="center">No portals configured yet.</Box>}
          />

          {availableCatalog.length > 0 && (
            <FormField label="Add a popular portal">
              <SpaceBetween direction="horizontal" size="xs">
                {availableCatalog.map((c) => (
                  <Button key={c.slug} onClick={() => enableKnownPortal(c)}>
                    {c.name}
                  </Button>
                ))}
              </SpaceBetween>
            </FormField>
          )}

          <ColumnLayout columns={2}>
            <FormField label="Custom portal name">
              <Input value={customName} onChange={({ detail }) => setCustomName(detail.value)} />
            </FormField>
            <FormField
              label="Webhook URL (optional)"
              description="If set, listings are POSTed here; otherwise the portal ingests the syndication feed."
            >
              <Input value={customUrl} onChange={({ detail }) => setCustomUrl(detail.value)} />
            </FormField>
          </ColumnLayout>
          <Box>
            <Button onClick={addCustomPortal}>Add custom portal</Button>
          </Box>

          {canSeeFeed && (
            <SpaceBetween size="s">
              <Header
                variant="h3"
                description="Portals configured in “feed” mode ingest this URL to pull your published listings automatically."
              >
                Your syndication feed
              </Header>
              {feedUrls ? (
                <>
                  <FormField
                    label="JSON feed URL"
                    description="Generic JSON feed of published listings."
                  >
                    <SpaceBetween direction="horizontal" size="xs">
                      <Input value={feedUrls.json} readOnly controlId="feed-json-url" ariaLabel="JSON feed URL" />
                      <Button
                        iconName="copy"
                        ariaLabel="Copy JSON feed URL"
                        onClick={() => copyFeedUrl(feedUrls.json)}
                      >
                        Copy
                      </Button>
                    </SpaceBetween>
                  </FormField>
                  <FormField label="XML feed URL" description="Property XML feed of published listings.">
                    <SpaceBetween direction="horizontal" size="xs">
                      <Input value={feedUrls.xml} readOnly controlId="feed-xml-url" ariaLabel="XML feed URL" />
                      <Button
                        iconName="copy"
                        ariaLabel="Copy XML feed URL"
                        onClick={() => copyFeedUrl(feedUrls.xml)}
                      >
                        Copy
                      </Button>
                    </SpaceBetween>
                  </FormField>
                </>
              ) : (
                <Box color="text-status-inactive">
                  Your syndication feed URL is unavailable because your account is not linked to an
                  organization.
                </Box>
              )}
            </SpaceBetween>
          )}
        </SpaceBetween>
      </Modal>

      {/* ── Syndicate a listing ────────────────────────────────────────── */}
      <EntityFormModal
        visible={syndicateModalOpen}
        onCancel={() => setSyndicateModalOpen(false)}
        title={syndicateListing ? `Syndicate: ${syndicateListing.title}` : 'Syndicate listing'}
        cancelLabel="Close"
        submitLabel="Post to selected"
        submitting={syndicating}
        onSubmit={runSyndication}
      >
        {enabledPortals.length === 0 ? (
          <Box textAlign="center">
            No enabled portals. Use “Manage portals” to add some first.
          </Box>
        ) : (
          <SpaceBetween size="s">
            {enabledPortals.map((p) => {
              const record = syndicationFor(p.id);
              return (
                <Box key={p.id}>
                  <Checkbox
                    checked={selectedPortalIds.includes(p.id)}
                    onChange={({ detail }) =>
                      setSelectedPortalIds((prev) =>
                        detail.checked ? [...prev, p.id] : prev.filter((x) => x !== p.id),
                      )
                    }
                  >
                    {p.name}
                    {record ? (
                      <>
                        {' '}
                        <Badge color={record.status === 'posted' ? 'green' : 'red'}>
                          {record.status}
                        </Badge>
                      </>
                    ) : null}
                  </Checkbox>
                </Box>
              );
            })}
          </SpaceBetween>
        )}
      </EntityFormModal>
    </SpaceBetween>
  );
};

export default VacancyListingsPage;
