import React, { useEffect, useState, useCallback } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Textarea from '@cloudscape-design/components/textarea';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Toggle from '@cloudscape-design/components/toggle';
import { useFlashbar } from '@/context/FlashbarContext';
import AIDocumentPrefill from '@/components/common/AIDocumentPrefill';
import { insuranceCertificates as certsApi, leases as leasesApi, vendors as vendorsApi, ai as aiApi } from '@/api';
import type { InsuranceCertificate, InsuranceCertComplianceSummary } from '@/types';

const CERT_TYPES = [
  { label: 'General Liability', value: 'general_liability' },
  { label: "Worker's Comp", value: 'workers_comp' },
  { label: 'Auto', value: 'auto' },
  { label: 'Umbrella', value: 'umbrella' },
  { label: 'Other', value: 'other' },
];

const statusBadge = (s: string) => {
  if (s === 'expired') return <Badge color="red">EXPIRED</Badge>;
  if (s === 'expiring_soon') return <Badge color="blue">EXPIRING SOON</Badge>;
  if (s === 'active') return <Badge color="green">ACTIVE</Badge>;
  return <Badge color="grey">UNKNOWN</Badge>;
};

interface EntityOption { label: string; value: string; kind: 'vendor' | 'landlord'; }

const InsuranceCertificatesPage: React.FC = () => {
  const { addFlashMessage } = useFlashbar();
  const [items, setItems] = useState<InsuranceCertificate[]>([]);
  const [compliance, setCompliance] = useState<InsuranceCertComplianceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [entityOptions, setEntityOptions] = useState<EntityOption[]>([]);

  // Filters
  const [filterExpired, setFilterExpired] = useState(false);
  const [filterExpiring, setFilterExpiring] = useState(false);

  // Modal
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    entity: null as EntityOption | null,
    certificate_type: 'general_liability',
    insurer: '',
    policy_number: '',
    effective_date: '',
    expiration_date: '',
    limits: '',
    certificate_holder: '',
    notes: '',
    is_verified: false,
    file: null as File | null,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (filterExpired) params.expired_only = true;
      if (filterExpiring) params.expiring_within_days = 30;
      const [certsRes, compRes] = await Promise.all([
        certsApi.list(params as Parameters<typeof certsApi.list>[0]),
        certsApi.compliance(),
      ]);
      setItems(certsRes.data);
      setCompliance(compRes.data);
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to load insurance certificates.' });
    } finally {
      setLoading(false);
    }
  }, [filterExpired, filterExpiring, addFlashMessage]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    vendorsApi.list({ page_size: 500 }).then((res) => {
      const opts: EntityOption[] = res.data.items.map((v) => ({
        label: `${v.company_name} (Vendor)`,
        value: v.id,
        kind: 'vendor' as const,
      }));
      setEntityOptions((prev) => [...opts, ...prev.filter((o) => o.kind === 'landlord')]);
    }).catch(() => {});
  }, []);

  const openCreate = () => {
    setEditingId(null);
    setForm({
      entity: null, certificate_type: 'general_liability', insurer: '', policy_number: '',
      effective_date: '', expiration_date: '', limits: '', certificate_holder: '', notes: '',
      is_verified: false, file: null,
    });
    setModalOpen(true);
  };

  const openEdit = (c: InsuranceCertificate) => {
    setEditingId(c.id);
    const entityOpt = entityOptions.find((o) => o.value === c.vendor_id || o.value === c.landlord_id) ?? null;
    setForm({
      entity: entityOpt,
      certificate_type: c.certificate_type,
      insurer: c.insurer ?? '',
      policy_number: c.policy_number ?? '',
      effective_date: c.effective_date ?? '',
      expiration_date: c.expiration_date ?? '',
      limits: c.limits ?? '',
      certificate_holder: c.certificate_holder ?? '',
      notes: c.notes ?? '',
      is_verified: c.is_verified,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!form.certificate_type || !form.entity) return;
    setSaving(true);
    try {
      const payload = {
        certificate_type: form.certificate_type,
        insurer: form.insurer || undefined,
        policy_number: form.policy_number || undefined,
        effective_date: form.effective_date || undefined,
        expiration_date: form.expiration_date || undefined,
        limits: form.limits || undefined,
        certificate_holder: form.certificate_holder || undefined,
        notes: form.notes || undefined,
        is_verified: form.is_verified,
        ...(form.entity.kind === 'vendor'
          ? { vendor_id: form.entity.value }
          : { landlord_id: form.entity.value }),
      };
      if (editingId) {
        await certsApi.update(editingId, payload);
        addFlashMessage({ type: 'success', content: 'Certificate updated.' });
      } else {
        await certsApi.create(payload);
        addFlashMessage({ type: 'success', content: 'Certificate added.' });
      }
      setModalOpen(false);
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to save certificate.' });
    } finally {
      setSaving(false);
    }
  };

  const applyAISuggestions = (suggested: Record<string, unknown>) => {
    const str = (v: unknown): string | undefined =>
      v === null || v === undefined ? undefined : String(v);
    // Map free-text coverage type onto one of the known select values.
    const mapCertType = (v: unknown): string | undefined => {
      const s = str(v);
      if (!s) return undefined;
      const lower = s.toLowerCase();
      const direct = CERT_TYPES.find((t) => t.value === lower);
      if (direct) return direct.value;
      if (lower.includes('general') || lower.includes('liab')) return 'general_liability';
      if (lower.includes('comp')) return 'workers_comp';
      if (lower.includes('auto')) return 'auto';
      if (lower.includes('umbrella') || lower.includes('excess')) return 'umbrella';
      return 'other';
    };
    setForm((f) => ({
      ...f,
      certificate_type: mapCertType(suggested.certificate_type) ?? f.certificate_type,
      insurer: str(suggested.insurer) ?? f.insurer,
      policy_number: str(suggested.policy_number) ?? f.policy_number,
      effective_date: str(suggested.effective_date) ?? f.effective_date,
      expiration_date: str(suggested.expiration_date) ?? f.expiration_date,
      limits: str(suggested.limits) ?? f.limits,
      certificate_holder: str(suggested.certificate_holder) ?? f.certificate_holder,
      notes: str(suggested.notes) ?? f.notes,
    }));
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('Delete this certificate?')) return;
    try {
      await certsApi.delete(id);
      addFlashMessage({ type: 'success', content: 'Certificate deleted.' });
      await load();
    } catch {
      addFlashMessage({ type: 'error', content: 'Failed to delete certificate.' });
    }
  };

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Track insurance certificates of insurance (COIs) for vendors and landlords."
          actions={<Button variant="primary" onClick={openCreate}>Add certificate</Button>}
        >
          Insurance Certificates
        </Header>
      }
    >
      <SpaceBetween size="l">
        {/* ── Compliance KPIs ── */}
        {compliance && (
          <Container header={<Header variant="h2">Compliance Summary</Header>}>
            <ColumnLayout columns={5} borders="vertical">
              {[
                ['Total', compliance.total, ''],
                ['Active', compliance.active, 'text-status-success'],
                ['Expiring Soon', compliance.expiring_soon, 'text-status-warning'],
                ['Expired', compliance.expired, 'text-status-error'],
                ['Unknown', compliance.unknown, 'text-body-secondary'],
              ].map(([label, count, color]) => (
                <Box textAlign="center" key={label as string}>
                  <Box fontWeight="bold" fontSize="body-s" color="text-body-secondary">{label}</Box>
                  <Box fontSize="heading-xl" color={(color as string) || undefined}>{count}</Box>
                </Box>
              ))}
            </ColumnLayout>
          </Container>
        )}

        {/* ── Filters ── */}
        <Container>
          <SpaceBetween direction="horizontal" size="l">
            <Toggle checked={filterExpired} onChange={({ detail }) => setFilterExpired(detail.checked)}>
              Show expired only
            </Toggle>
            <Toggle checked={filterExpiring} onChange={({ detail }) => setFilterExpiring(detail.checked)}>
              Expiring within 30 days
            </Toggle>
          </SpaceBetween>
        </Container>

        {/* ── Table ── */}
        <Table
          loading={loading}
          items={items}
          columnDefinitions={[
            {
              id: 'entity',
              header: 'Vendor / Landlord',
              cell: (c: InsuranceCertificate) =>
                c.vendor?.company_name ?? c.landlord?.company_name ?? '—',
            },
            {
              id: 'type',
              header: 'Type',
              cell: (c: InsuranceCertificate) => (
                <Badge color="blue">
                  {CERT_TYPES.find((t) => t.value === c.certificate_type)?.label ?? c.certificate_type}
                </Badge>
              ),
            },
            { id: 'insurer', header: 'Insurer', cell: (c: InsuranceCertificate) => c.insurer ?? '—' },
            { id: 'policy', header: 'Policy #', cell: (c: InsuranceCertificate) => c.policy_number ?? '—' },
            { id: 'effective', header: 'Effective', cell: (c: InsuranceCertificate) => c.effective_date ?? '—' },
            { id: 'expiration', header: 'Expires', cell: (c: InsuranceCertificate) => c.expiration_date ?? '—' },
            {
              id: 'status',
              header: 'Status',
              cell: (c: InsuranceCertificate) => statusBadge(c.status),
              width: 140,
            },
            {
              id: 'verified',
              header: 'Verified',
              cell: (c: InsuranceCertificate) => (
                <StatusIndicator type={c.is_verified ? 'success' : 'stopped'}>
                  {c.is_verified ? 'Yes' : 'No'}
                </StatusIndicator>
              ),
              width: 90,
            },
            {
              id: 'actions',
              header: '',
              cell: (c: InsuranceCertificate) => (
                <SpaceBetween direction="horizontal" size="xs">
                  <Button variant="inline-link" onClick={() => openEdit(c)}>Edit</Button>
                  <Button variant="inline-link" onClick={() => handleDelete(c.id)}>Delete</Button>
                </SpaceBetween>
              ),
              width: 120,
            },
          ]}
          empty={
            <Box textAlign="center" color="inherit" padding="l">
              <b>No certificates</b>
              <Box color="text-body-secondary" padding={{ bottom: 's' }}>
                Add COIs to track compliance for vendors and landlords.
              </Box>
            </Box>
          }
          header={<Header counter={`(${items.length})`}>Certificates of Insurance</Header>}
        />
      </SpaceBetween>

      {/* ── Create / Edit Modal ── */}
      <Modal
        visible={modalOpen}
        onDismiss={() => setModalOpen(false)}
        header={editingId ? 'Edit certificate' : 'Add insurance certificate'}
        size="large"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button
                variant="primary"
                loading={saving}
                onClick={handleSave}
                disabled={!form.entity || !form.certificate_type}
              >
                {editingId ? 'Save changes' : 'Add certificate'}
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          {!editingId && (
            <AIDocumentPrefill
              title="AI assist — extract from document"
              description="Upload a certificate of insurance and let AI pre-fill the fields below for your review."
              dropzoneText="Drop a certificate of insurance here"
              parse={aiApi.parseInsuranceCertificate}
              onSuggested={applyAISuggestions}
              onFileExtracted={(file) => setForm((f) => ({ ...f, file }))}
            />
          )}
          <FormField label="Vendor or landlord" description="Required">
            <Select
              selectedOption={form.entity ? { label: form.entity.label, value: form.entity.value } : null}
              onChange={({ detail }) => {
                const opt = entityOptions.find((o) => o.value === detail.selectedOption?.value) ?? null;
                setForm((f) => ({ ...f, entity: opt }));
              }}
              options={entityOptions.map((o) => ({ label: o.label, value: o.value }))}
              placeholder="Select vendor or landlord"
              filteringType="auto"
            />
          </FormField>

          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Certificate type">
              <Select
                selectedOption={CERT_TYPES.find((t) => t.value === form.certificate_type) ?? null}
                onChange={({ detail }) => setForm((f) => ({ ...f, certificate_type: detail.selectedOption?.value ?? 'general_liability' }))}
                options={CERT_TYPES}
              />
            </FormField>
            <FormField label="Policy number">
              <Input
                value={form.policy_number}
                onChange={({ detail }) => setForm((f) => ({ ...f, policy_number: detail.value }))}
                placeholder="e.g., GL-123456"
              />
            </FormField>
          </SpaceBetween>

          <FormField label="Insurer">
            <Input
              value={form.insurer}
              onChange={({ detail }) => setForm((f) => ({ ...f, insurer: detail.value }))}
              placeholder="e.g., Travelers Insurance"
            />
          </FormField>

          <SpaceBetween direction="horizontal" size="m">
            <FormField label="Effective date">
              <Input
                value={form.effective_date}
                onChange={({ detail }) => setForm((f) => ({ ...f, effective_date: detail.value }))}
                type="date"
              />
            </FormField>
            <FormField label="Expiration date">
              <Input
                value={form.expiration_date}
                onChange={({ detail }) => setForm((f) => ({ ...f, expiration_date: detail.value }))}
                type="date"
              />
            </FormField>
          </SpaceBetween>

          <FormField label="Coverage limits">
            <Input
              value={form.limits}
              onChange={({ detail }) => setForm((f) => ({ ...f, limits: detail.value }))}
              placeholder="e.g., $1M/$2M"
            />
          </FormField>

          <FormField label="Certificate holder">
            <Input
              value={form.certificate_holder}
              onChange={({ detail }) => setForm((f) => ({ ...f, certificate_holder: detail.value }))}
              placeholder="Your organization name"
            />
          </FormField>

          <FormField label="Notes">
            <Textarea
              value={form.notes}
              onChange={({ detail }) => setForm((f) => ({ ...f, notes: detail.value }))}
              rows={3}
            />
          </FormField>

          <FormField label="Certificate PDF">
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png"
              onChange={(e) => setForm((f) => ({ ...f, file: e.target.files?.[0] ?? null }))}
              style={{ display: 'block', marginBottom: '8px' }}
            />
            <Box fontSize="body-s" color="text-body-secondary">
              Upload a PDF or image of the certificate of insurance
            </Box>
          </FormField>

          <Toggle
            checked={form.is_verified}
            onChange={({ detail }) => setForm((f) => ({ ...f, is_verified: detail.checked }))}
          >
            Verified
          </Toggle>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default InsuranceCertificatesPage;
