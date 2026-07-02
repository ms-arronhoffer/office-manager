import React, { useCallback, useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Toggle from '@cloudscape-design/components/toggle';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Modal from '@cloudscape-design/components/modal';
import { useFlashbar } from '@/context/FlashbarContext';
import { tax as taxApi } from '@/api';
import type { Vendor1099Summary, Vendor1099Detail } from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const FORM_OPTIONS = [
  { label: 'All forms', value: '' },
  { label: '1099-NEC', value: '1099-NEC' },
  { label: '1099-MISC', value: '1099-MISC' },
];

const Tax1099Page: React.FC = () => {
  const { addFlash } = useFlashbar();
  const currentYear = new Date().getFullYear();

  const [year, setYear] = useState(String(currentYear - 1));
  const [form, setForm] = useState('');
  const [onlyReportable, setOnlyReportable] = useState(false);
  const [rows, setRows] = useState<Vendor1099Summary[]>([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<Vendor1099Detail | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: { year: number; form?: string; only_reportable?: boolean } = {
        year: Number(year),
      };
      if (form) params.form = form;
      if (onlyReportable) params.only_reportable = true;
      const resp = await taxApi.list1099(params);
      setRows(resp.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load 1099 summary.' });
    } finally {
      setLoading(false);
    }
  }, [year, form, onlyReportable, addFlash]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (vendorId: string) => {
    try {
      const resp = await taxApi.get1099Detail(vendorId, Number(year));
      setDetail(resp.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load vendor 1099 detail.' });
    }
  };

  const exportCsv = async () => {
    try {
      const params: { year: number; form?: string; only_reportable?: boolean } = {
        year: Number(year),
        only_reportable: onlyReportable,
      };
      if (form) params.form = form;
      const resp = await taxApi.export1099(params);
      const url = window.URL.createObjectURL(resp.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `1099_${year}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      addFlash({ type: 'error', content: 'Failed to export 1099 CSV.' });
    }
  };

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Prepare 1099-NEC / 1099-MISC totals from recorded vendor payments"
          actions={
            <Button iconName="download" onClick={exportCsv}>
              Export CSV
            </Button>
          }
        >
          Tax / 1099
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Container>
          <SpaceBetween direction="horizontal" size="l">
            <FormField label="Tax year">
              <Input
                type="number"
                value={year}
                onChange={(e) => setYear(e.detail.value)}
              />
            </FormField>
            <FormField label="Form">
              <Select
                selectedOption={FORM_OPTIONS.find((o) => o.value === form) ?? FORM_OPTIONS[0]}
                onChange={(e) => setForm(e.detail.selectedOption.value ?? '')}
                options={FORM_OPTIONS}
              />
            </FormField>
            <FormField label="Threshold">
              <Toggle
                checked={onlyReportable}
                onChange={(e) => setOnlyReportable(e.detail.checked)}
              >
                Only vendors meeting the filing threshold
              </Toggle>
            </FormField>
          </SpaceBetween>
        </Container>

        <Table<Vendor1099Summary>
          loading={loading}
          items={rows}
          variant="container"
          header={<Header counter={`(${rows.length})`}>Reportable vendors</Header>}
          empty={<Box textAlign="center" padding="l">No reportable payments for {year}.</Box>}
          columnDefinitions={[
            {
              id: 'vendor',
              header: 'Vendor',
              cell: (r) => (
                <Button variant="link" onClick={() => openDetail(r.vendor_id)}>
                  {r.legal_name || r.vendor_name}
                </Button>
              ),
            },
            { id: 'tax_id', header: 'Tax ID', cell: (r) => r.tax_id ?? '—' },
            {
              id: 'boxes',
              header: 'Boxes',
              cell: (r) =>
                r.boxes.map((b) => `${b.form} ${fmt(b.amount)}`).join(', ') || '—',
            },
            { id: 'total', header: 'Total', cell: (r) => fmt(r.total) },
            { id: 'count', header: 'Payments', cell: (r) => r.payment_count },
            {
              id: 'threshold',
              header: 'Status',
              cell: (r) =>
                r.meets_threshold ? (
                  <Badge color="green">Filing required</Badge>
                ) : (
                  <Badge color="grey">Below threshold</Badge>
                ),
            },
          ]}
        />
      </SpaceBetween>

      <Modal
        visible={detail !== null}
        onDismiss={() => setDetail(null)}
        header={detail ? `${detail.legal_name} — ${detail.year} 1099` : ''}
        size="large"
      >
        {detail && (
          <SpaceBetween size="m">
            <Box>
              <strong>Tax ID:</strong> {detail.tax_id ?? '—'} · <strong>Total:</strong>{' '}
              {fmt(detail.total)}
            </Box>
            <Table<Vendor1099Detail['payments'][number]>
              items={detail.payments}
              columnDefinitions={[
                { id: 'date', header: 'Date', cell: (p) => p.payment_date },
                { id: 'amount', header: 'Amount', cell: (p) => fmt(p.amount) },
                {
                  id: 'reportable',
                  header: 'Reportable',
                  cell: (p) =>
                    p.reportable ? <Badge color="green">Yes</Badge> : <Badge color="grey">No</Badge>,
                },
                { id: 'box', header: 'Box', cell: (p) => p.box ?? '—' },
                { id: 'reference', header: 'Reference', cell: (p) => p.reference ?? '—' },
              ]}
              empty={<Box textAlign="center" padding="l">No payments.</Box>}
            />
          </SpaceBetween>
        )}
      </Modal>
    </ContentLayout>
  );
};

export default Tax1099Page;
