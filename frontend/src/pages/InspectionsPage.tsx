import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import CreateWizardModal from '@/components/common/CreateWizardModal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import DatePicker from '@cloudscape-design/components/date-picker';
import Textarea from '@cloudscape-design/components/textarea';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Tabs from '@cloudscape-design/components/tabs';
import Checkbox from '@cloudscape-design/components/checkbox';
import SegmentedControl from '@cloudscape-design/components/segmented-control';
import { useFlashbar } from '@/context/FlashbarContext';
import { useAuth } from '@/auth/AuthContext';
import { inspections as inspectionsApi, offices as officesApi } from '@/api';
import useListCollection from '@/hooks/useListCollection';
import type {
  Inspection,
  InspectionItemResultInput,
  InspectionResult,
  InspectionTemplate,
  InspectionTemplateItemInput,
  Office,
} from '@/types';

const resultBadge = (r: InspectionResult | null) => {
  if (!r) return <Box color="text-status-inactive">—</Box>;
  const color = r === 'pass' ? 'green' : r === 'fail' ? 'red' : 'grey';
  const label = r === 'na' ? 'N/A' : r;
  return <Badge color={color as 'green' | 'red' | 'grey'}>{label}</Badge>;
};

const statusBadge = (s: string) => {
  const color =
    s === 'completed' ? 'green' : s === 'in_progress' ? 'blue' : s === 'canceled' ? 'grey' : 'blue';
  return <Badge color={color as 'green' | 'blue' | 'grey'}>{s.replace('_', ' ')}</Badge>;
};

interface ItemDraft {
  label: string;
  description: string;
  is_required: boolean;
}

const InspectionsPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [tab, setTab] = useState<string>('inspections');
  const [items, setItems] = useState<Inspection[]>([]);
  const [templates, setTemplates] = useState<InspectionTemplate[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [loading, setLoading] = useState(true);

  // Template editor state
  const [templateModal, setTemplateModal] = useState(false);
  const [tplName, setTplName] = useState('');
  const [tplCategory, setTplCategory] = useState('');
  const [tplItems, setTplItems] = useState<ItemDraft[]>([{ label: '', description: '', is_required: true }]);

  // Inspection creation state
  const [inspectionModal, setInspectionModal] = useState(false);
  const [insTitle, setInsTitle] = useState('');
  const [insOfficeId, setInsOfficeId] = useState('');
  const [insTemplateId, setInsTemplateId] = useState('');
  const [insScheduled, setInsScheduled] = useState('');

  // Inspection detail/scoring state
  const [detail, setDetail] = useState<Inspection | null>(null);

  const officeName = useCallback(
    (id: string) => {
      const o = offices.find((x) => x.id === id);
      return o ? `#${o.office_number} ${o.location_name}` : id;
    },
    [offices],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [insRes, tplRes, offRes] = await Promise.all([
        inspectionsApi.list(),
        inspectionsApi.listTemplates(),
        officesApi.list({ page_size: 1000 }),
      ]);
      setItems(insRes.data);
      setTemplates(tplRes.data);
      setOffices(offRes.data.items);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load inspections.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    void load();
  }, [load]);

  // ─── Template creation ──────────────────────────────────────────────────────
  const openTemplateModal = () => {
    setTplName('');
    setTplCategory('');
    setTplItems([{ label: '', description: '', is_required: true }]);
    setTemplateModal(true);
  };

  const saveTemplate = async () => {
    const cleanItems: InspectionTemplateItemInput[] = tplItems
      .filter((i) => i.label.trim())
      .map((i, idx) => ({
        label: i.label.trim(),
        description: i.description.trim() || null,
        sort_order: idx,
        is_required: i.is_required,
      }));
    if (!tplName.trim() || cleanItems.length === 0) {
      addFlash({ type: 'error', content: 'A template needs a name and at least one item.' });
      return;
    }
    try {
      await inspectionsApi.createTemplate({
        name: tplName.trim(),
        category: tplCategory.trim() || null,
        items: cleanItems,
      });
      addFlash({ type: 'success', content: 'Template created.' });
      setTemplateModal(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to create template.' });
    }
  };

  const deleteTemplate = async (id: string) => {
    try {
      await inspectionsApi.removeTemplate(id);
      addFlash({ type: 'success', content: 'Template deleted.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete template.' });
    }
  };

  // ─── Inspection creation ────────────────────────────────────────────────────
  const openInspectionModal = () => {
    setInsTitle('');
    setInsOfficeId('');
    setInsTemplateId('');
    setInsScheduled('');
    setInspectionModal(true);
  };

  const saveInspection = async () => {
    if (!insTitle.trim() || !insOfficeId) {
      addFlash({ type: 'error', content: 'Title and office are required.' });
      return;
    }
    try {
      await inspectionsApi.create({
        title: insTitle.trim(),
        office_id: insOfficeId,
        template_id: insTemplateId || null,
        scheduled_date: insScheduled || null,
      });
      addFlash({ type: 'success', content: 'Inspection scheduled.' });
      setInspectionModal(false);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to create inspection.' });
    }
  };

  // ─── Scoring ────────────────────────────────────────────────────────────────
  const openDetail = async (id: string) => {
    try {
      const res = await inspectionsApi.get(id);
      setDetail(res.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load inspection.' });
    }
  };

  const setResult = (resultId: string, value: InspectionResult) => {
    setDetail((d) =>
      d
        ? { ...d, results: d.results.map((r) => (r.id === resultId ? { ...r, result: value } : r)) }
        : d,
    );
  };

  const setResultNotes = (resultId: string, notes: string) => {
    setDetail((d) =>
      d ? { ...d, results: d.results.map((r) => (r.id === resultId ? { ...r, notes } : r)) } : d,
    );
  };

  const saveScores = async () => {
    if (!detail) return;
    const updates: InspectionItemResultInput[] = detail.results.map((r) => ({
      id: r.id,
      result: r.result,
      notes: r.notes,
    }));
    try {
      const res = await inspectionsApi.update(detail.id, { results: updates });
      setDetail(res.data);
      addFlash({ type: 'success', content: 'Results saved.' });
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save results.' });
    }
  };

  const completeInspection = async () => {
    if (!detail) return;
    try {
      const res = await inspectionsApi.complete(detail.id);
      setDetail(res.data);
      addFlash({ type: 'success', content: `Inspection completed — ${res.data.overall_result}.` });
      await load();
    } catch {
      addFlash({
        type: 'error',
        content: 'Could not complete — all required items must be scored first.',
      });
    }
  };

  const templateOptions = useMemo(
    () => [
      { label: 'No template (blank)', value: '' },
      ...templates.map((t) => ({ label: t.name, value: t.id })),
    ],
    [templates],
  );

  const officeOptions = useMemo(
    () => offices.map((o) => ({ label: `#${o.office_number} ${o.location_name}`, value: o.id })),
    [offices],
  );

  const detailLocked = detail?.status === 'completed';

  const inspectionCollection = useListCollection(items, {
    entity: 'inspections',
    filterPlaceholder: 'Search inspections',
    searchText: (i) =>
      [i.title, officeName(i.office_id), i.status, i.scheduled_date, i.overall_result]
        .filter(Boolean)
        .join(' '),
    empty: <Box textAlign="center">No inspections yet.</Box>,
  });

  const templateCollection = useListCollection(templates, {
    entity: 'inspection-templates',
    filterPlaceholder: 'Search templates',
    searchText: (t) => [t.name, t.category].filter(Boolean).join(' '),
    empty: <Box textAlign="center">No templates yet.</Box>,
  });

  const templateBasicsFields = (
    <SpaceBetween size="m">
      <FormField label="Name">
        <Input value={tplName} onChange={({ detail: d }) => setTplName(d.value)} />
      </FormField>
      <FormField label="Category" description="Optional grouping, e.g. hvac, safety.">
        <Input value={tplCategory} onChange={({ detail: d }) => setTplCategory(d.value)} />
      </FormField>
    </SpaceBetween>
  );

  const templateItemFields = (
    <FormField label="Checklist items">
      <SpaceBetween size="xs">
        {tplItems.map((item, idx) => (
          <SpaceBetween key={idx} direction="horizontal" size="xs">
            <Input
              placeholder="Item label"
              value={item.label}
              onChange={({ detail: d }) =>
                setTplItems((prev) =>
                  prev.map((p, i) => (i === idx ? { ...p, label: d.value } : p)),
                )
              }
            />
            <Checkbox
              checked={item.is_required}
              onChange={({ detail: d }) =>
                setTplItems((prev) =>
                  prev.map((p, i) => (i === idx ? { ...p, is_required: d.checked } : p)),
                )
              }
            >
              Required
            </Checkbox>
            <Button
              variant="inline-link"
              onClick={() => setTplItems((prev) => prev.filter((_, i) => i !== idx))}
            >
              Remove
            </Button>
          </SpaceBetween>
        ))}
        <Button
          onClick={() =>
            setTplItems((prev) => [...prev, { label: '', description: '', is_required: true }])
          }
        >
          Add item
        </Button>
      </SpaceBetween>
    </FormField>
  );

  const inspectionBasicsFields = (
    <SpaceBetween size="m">
      <FormField label="Title">
        <Input value={insTitle} onChange={({ detail: d }) => setInsTitle(d.value)} />
      </FormField>
      <FormField label="Office">
        <Select
          selectedOption={officeOptions.find((o) => o.value === insOfficeId) ?? null}
          onChange={({ detail: d }) => setInsOfficeId(d.selectedOption.value ?? '')}
          options={officeOptions}
          placeholder="Select an office"
          filteringType="auto"
        />
      </FormField>
    </SpaceBetween>
  );

  const inspectionScheduleFields = (
    <SpaceBetween size="m">
      <FormField label="Template" description="Items are copied onto the inspection.">
        <Select
          selectedOption={templateOptions.find((o) => o.value === insTemplateId) ?? templateOptions[0]}
          onChange={({ detail: d }) => setInsTemplateId(d.selectedOption.value ?? '')}
          options={templateOptions}
        />
      </FormField>
      <FormField label="Scheduled date">
        <DatePicker
          value={insScheduled}
          onChange={({ detail: d }) => setInsScheduled(d.value)}
          placeholder="YYYY/MM/DD"
        />
      </FormField>
    </SpaceBetween>
  );

  const templateDirty = Boolean(
    tplName || tplCategory || tplItems.some((i) => i.label.trim() || i.description.trim()),
  );

  const inspectionDirty = Boolean(insTitle || insOfficeId || insTemplateId || insScheduled);

  return (
    <ContentLayout header={<Header variant="h1">Property Inspections</Header>}>
      <Tabs
        activeTabId={tab}
        onChange={({ detail: d }) => setTab(d.activeTabId)}
        tabs={[
          {
            id: 'inspections',
            label: 'Inspections',
            content: (
              <Container
                header={
                  <Header
                    variant="h2"
                    actions={
                      canEdit ? (
                        <Button variant="primary" onClick={openInspectionModal}>
                          New inspection
                        </Button>
                      ) : undefined
                    }
                  >
                    Inspections
                  </Header>
                }
              >
                <Table
                  {...inspectionCollection.collectionProps}
                  loading={loading}
                  items={inspectionCollection.items}
                  filter={inspectionCollection.filter}
                  pagination={inspectionCollection.pagination}
                  columnDefinitions={[
                    {
                      id: 'title',
                      header: 'Title',
                      cell: (i) => (
                        <Button variant="link" onClick={() => openDetail(i.id)}>
                          {i.title}
                        </Button>
                      ),
                    },
                    { id: 'office', header: 'Office', cell: (i) => officeName(i.office_id) },
                    { id: 'status', header: 'Status', cell: (i) => statusBadge(i.status) },
                    { id: 'scheduled', header: 'Scheduled', cell: (i) => i.scheduled_date ?? '—' },
                    {
                      id: 'overall',
                      header: 'Result',
                      cell: (i) => resultBadge(i.overall_result),
                    },
                  ]}
                />
              </Container>
            ),
          },
          {
            id: 'templates',
            label: 'Templates',
            content: (
              <Container
                header={
                  <Header
                    variant="h2"
                    actions={
                      canEdit ? (
                        <Button variant="primary" onClick={openTemplateModal}>
                          New template
                        </Button>
                      ) : undefined
                    }
                  >
                    Checklist templates
                  </Header>
                }
              >
                <Table
                  {...templateCollection.collectionProps}
                  loading={loading}
                  items={templateCollection.items}
                  filter={templateCollection.filter}
                  pagination={templateCollection.pagination}
                  columnDefinitions={[
                    { id: 'name', header: 'Name', cell: (t) => t.name },
                    { id: 'category', header: 'Category', cell: (t) => t.category ?? '—' },
                    { id: 'items', header: 'Items', cell: (t) => t.items.length },
                    {
                      id: 'active',
                      header: 'Active',
                      cell: (t) => (t.is_active ? 'Yes' : 'No'),
                    },
                    {
                      id: 'actions',
                      header: '',
                      cell: (t) =>
                        canEdit ? (
                          <Button variant="inline-link" onClick={() => deleteTemplate(t.id)}>
                            Delete
                          </Button>
                        ) : null,
                    },
                  ]}
                />
              </Container>
            ),
          },
        ]}
      />

      {/* Template creation wizard */}
      <CreateWizardModal
        visible={templateModal}
        entityLabel="inspection template"
        onCancel={() => setTemplateModal(false)}
        onSubmit={saveTemplate}
        dirty={templateDirty}
        steps={[
          {
            title: 'Template basics',
            description: 'Name the checklist and group it with similar ones.',
            content: templateBasicsFields,
            validate: () =>
              !tplName.trim() ? 'A template needs a name and at least one item.' : null,
          },
          {
            title: 'Checklist items',
            description: 'What gets scored on every inspection using this template.',
            content: templateItemFields,
            validate: () =>
              tplItems.every((i) => !i.label.trim())
                ? 'A template needs a name and at least one item.'
                : null,
          },
        ]}
      />

      {/* Inspection creation wizard */}
      <CreateWizardModal
        visible={inspectionModal}
        entityLabel="inspection"
        onCancel={() => setInspectionModal(false)}
        onSubmit={saveInspection}
        dirty={inspectionDirty}
        steps={[
          {
            title: 'Inspection details',
            description: 'What is being inspected, and where.',
            content: inspectionBasicsFields,
            validate: () =>
              !insTitle.trim() || !insOfficeId ? 'Title and office are required.' : null,
          },
          {
            title: 'Checklist & schedule',
            description: 'Pick a checklist template and when the visit happens.',
            content: inspectionScheduleFields,
          },
        ]}
      />

      {/* Inspection detail / scoring modal */}
      <Modal
        visible={detail !== null}
        onDismiss={() => setDetail(null)}
        header={detail ? detail.title : ''}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setDetail(null)}>
                Close
              </Button>
              {canEdit && !detailLocked && (
                <>
                  <Button onClick={saveScores}>Save results</Button>
                  <Button variant="primary" onClick={completeInspection}>
                    Complete
                  </Button>
                </>
              )}
            </SpaceBetween>
          </Box>
        }
      >
        {detail && (
          <SpaceBetween size="m">
            <SpaceBetween direction="horizontal" size="l">
              <Box>Status: {statusBadge(detail.status)}</Box>
              <Box>Office: {officeName(detail.office_id)}</Box>
              {detail.overall_result && <Box>Overall: {resultBadge(detail.overall_result)}</Box>}
            </SpaceBetween>
            <Table
              items={detail.results}
              columnDefinitions={[
                {
                  id: 'label',
                  header: 'Item',
                  cell: (r) => (
                    <span>
                      {r.label}
                      {r.is_required && <Box variant="span" color="text-status-error"> *</Box>}
                    </span>
                  ),
                },
                {
                  id: 'result',
                  header: 'Result',
                  cell: (r) =>
                    detailLocked ? (
                      resultBadge(r.result)
                    ) : (
                      <SegmentedControl
                        selectedId={r.result ?? ''}
                        onChange={({ detail: d }) =>
                          setResult(r.id, d.selectedId as InspectionResult)
                        }
                        options={[
                          { id: 'pass', text: 'Pass' },
                          { id: 'fail', text: 'Fail' },
                          { id: 'na', text: 'N/A' },
                        ]}
                      />
                    ),
                },
                {
                  id: 'notes',
                  header: 'Notes',
                  cell: (r) =>
                    detailLocked ? (
                      r.notes ?? '—'
                    ) : (
                      <Textarea
                        rows={1}
                        value={r.notes ?? ''}
                        onChange={({ detail: d }) => setResultNotes(r.id, d.value)}
                      />
                    ),
                },
              ]}
              empty={<Box textAlign="center">This inspection has no checklist items.</Box>}
            />
          </SpaceBetween>
        )}
      </Modal>
    </ContentLayout>
  );
};

export default InspectionsPage;
