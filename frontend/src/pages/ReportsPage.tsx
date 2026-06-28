import React, { useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import FormField from '@cloudscape-design/components/form-field';
import Select from '@cloudscape-design/components/select';
import Multiselect from '@cloudscape-design/components/multiselect';
import RadioGroup from '@cloudscape-design/components/radio-group';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Table from '@cloudscape-design/components/table';
import Input from '@cloudscape-design/components/input';
import Modal from '@cloudscape-design/components/modal';
import TokenGroup from '@cloudscape-design/components/token-group';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { reports, leases as leasesApi } from '@/api';
import AISummaryPanel from '@/components/common/AISummaryPanel';
import type { ReportTemplate, FilterConfig, LeasePortfolioResponse, RentRollRow } from '@/types';

type Format = 'pdf' | 'csv' | 'xlsx';

interface SelectOption {
  label: string;
  value: string;
}

interface PreviewRow {
  _idx: number;
  [key: string]: unknown;
}

interface PreviewState {
  title: string;
  headers: string[];
  headerKeys: string[];
  rows: PreviewRow[];
  total: number;
}

const ALL_OPTION = { value: '', label: 'All' };

function formatCurrency(value: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: 2 }).format(value);
}

function formatPct(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${(value * 100).toFixed(4)}%`;
}

const ReportsPage: React.FC = () => {
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [templateError, setTemplateError] = useState<string | null>(null);

  const [selectedTemplate, setSelectedTemplate] = useState<SelectOption | null>(null);
  const [selectedColumns, setSelectedColumns] = useState<SelectOption[]>([]);
  const [format, setFormat] = useState<Format>('pdf');
  const [filters, setFilters] = useState<Record<string, string>>({});

  const [previewing, setPreviewing] = useState(false);
  const [previewData, setPreviewData] = useState<PreviewState | null>(null);

  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Email modal state
  const [emailModalVisible, setEmailModalVisible] = useState(false);
  const [emailRecipients, setEmailRecipients] = useState<string[]>([]);
  const [emailInput, setEmailInput] = useState('');
  const [emailing, setEmailing] = useState(false);
  const [emailResult, setEmailResult] = useState<string | null>(null);

  // Lease Accounting Portfolio
  const [portfolio, setPortfolio] = useState<LeasePortfolioResponse | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);

  // Accounting export state
  const [selectedAmortizationLease, setSelectedAmortizationLease] = useState<SelectOption | null>(null);
  const [exportingAmortization, setExportingAmortization] = useState(false);
  const [exportingMaturity, setExportingMaturity] = useState(false);
  const [exportingRentRoll, setExportingRentRoll] = useState(false);
  const [accountingExportError, setAccountingExportError] = useState<string | null>(null);

  useEffect(() => {
    const fetchTemplates = async () => {
      setLoadingTemplates(true);
      setTemplateError(null);
      try {
        const res = await reports.getTemplates();
        setTemplates(res.data);
      } catch {
        setTemplateError('Failed to load report templates.');
      } finally {
        setLoadingTemplates(false);
      }
    };
    fetchTemplates();
  }, []);

  useEffect(() => {
    const fetchPortfolio = async () => {
      setPortfolioLoading(true);
      setPortfolioError(null);
      try {
        const res = await reports.leaseAccountingPortfolio();
        setPortfolio(res.data);
      } catch {
        setPortfolioError('Failed to load lease accounting portfolio.');
      } finally {
        setPortfolioLoading(false);
      }
    };
    fetchPortfolio();
  }, []);

  const templateOptions: SelectOption[] = templates.map((t) => ({
    label: t.title,
    value: t.id,
  }));

  const activeTemplate = selectedTemplate
    ? templates.find((t) => t.id === selectedTemplate.value) ?? null
    : null;

  const columnOptions: SelectOption[] = activeTemplate
    ? activeTemplate.columns.map((c) => ({ label: c.label, value: c.key }))
    : [];

  const filtersConfig: FilterConfig[] = activeTemplate?.filters_config ?? [];

  const handleTemplateChange = (option: SelectOption | null) => {
    setSelectedTemplate(option);
    setError(null);
    setPreviewData(null);
    setFilters({});
    if (option) {
      const tmpl = templates.find((t) => t.id === option.value);
      if (tmpl) {
        setSelectedColumns(tmpl.columns.map((c) => ({ label: c.label, value: c.key })));
      }
    } else {
      setSelectedColumns([]);
    }
  };

  const buildFilters = (): Record<string, unknown> | undefined => {
    const active: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(filters)) {
      if (value !== '' && value !== undefined) {
        active[key] = value;
      }
    }
    return Object.keys(active).length > 0 ? active : undefined;
  };

  const handlePreview = async () => {
    if (!selectedTemplate || selectedColumns.length === 0) return;
    setPreviewing(true);
    setError(null);
    try {
      const res = await reports.preview({
        dataset: selectedTemplate.value,
        columns: selectedColumns.map((c) => c.value),
        filters: buildFilters(),
      });
      const data = res.data;
      const headerKeys = data.headers.map((_: string, i: number) => `col_${i}`);
      const rows: PreviewRow[] = data.rows.map((row: unknown[], idx: number) => {
        const obj: PreviewRow = { _idx: idx };
        row.forEach((val, colIdx) => {
          obj[headerKeys[colIdx]] = val;
        });
        return obj;
      });
      setPreviewData({ title: data.title, headers: data.headers, headerKeys, rows, total: data.total });
    } catch {
      setError('Failed to load preview.');
    } finally {
      setPreviewing(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedTemplate || selectedColumns.length === 0) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await reports.generate({
        dataset: selectedTemplate.value,
        columns: selectedColumns.map((c) => c.value),
        format,
        filters: buildFilters(),
      });

      const mimeTypes: Record<Format, string> = {
        pdf: 'application/pdf',
        csv: 'text/csv',
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      };

      const blob = new Blob([res.data], { type: mimeTypes[format] });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `report-${selectedTemplate.value}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch {
      setError('Failed to generate the report.');
    } finally {
      setGenerating(false);
    }
  };

  const handlePrint = () => {
    if (!previewData) return;

    const printWindow = window.open('', '_blank');
    if (!printWindow) return;

    const tableHtml = `
      <table>
        <thead><tr>${previewData.headers.map((h) => `<th>${h}</th>`).join('')}</tr></thead>
        <tbody>${previewData.rows.map((row) =>
          `<tr>${previewData.headerKeys.map((k) => `<td>${row[k] ?? ''}</td>`).join('')}</tr>`
        ).join('')}</tbody>
      </table>`;

    printWindow.document.write(`<!DOCTYPE html><html><head>
      <title>${previewData.title}</title>
      <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { font-size: 18px; margin-bottom: 4px; }
        .meta { font-size: 12px; color: #666; margin-bottom: 12px; }
        table { width: 100%; border-collapse: collapse; font-size: 11px; }
        th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
        th { background: #f0f0f0; font-weight: bold; }
        tr:nth-child(even) { background: #fafafa; }
      </style>
    </head><body>
      <h1>${previewData.title}</h1>
      <div class="meta">${previewData.total} records &bull; ${new Date().toLocaleDateString()}</div>
      ${tableHtml}
    </body></html>`);
    printWindow.document.close();
    printWindow.focus();
    printWindow.print();
  };

  // ─── Email ──────────────────────────────────────────────────────────────────

  const buildEmailHtml = (): string => {
    if (!previewData) return '';
    const date = new Date().toLocaleDateString();

    const tableRows = previewData.rows.map((row, rIdx) => {
      const bgColor = rIdx % 2 === 0 ? '#ffffff' : '#f9f9f9';
      const cells = previewData.headerKeys.map((k) =>
        `<td style="border:1px solid #ddd;padding:6px 10px;">${row[k] ?? ''}</td>`
      ).join('');
      return `<tr style="background:${bgColor}">${cells}</tr>`;
    }).join('');

    return [
      `<html><body style="font-family:Arial,sans-serif;color:#333;">`,
      `<h2 style="margin:0 0 4px;">${previewData.title}</h2>`,
      `<p style="font-size:13px;color:#666;margin:0 0 16px;">${date} &mdash; ${previewData.total} records</p>`,
      `<table style="border-collapse:collapse;width:100%;font-size:13px;">`,
      `<thead><tr style="background:#0073bb;color:#fff;">`,
      previewData.headers.map((h) =>
        `<th style="border:1px solid #ddd;padding:8px 10px;text-align:left;">${h}</th>`
      ).join(''),
      `</tr></thead>`,
      `<tbody>${tableRows}</tbody>`,
      `</table>`,
      `<p style="font-size:11px;color:#999;margin-top:16px;">PDF report attached.</p>`,
      `</body></html>`,
    ].join('');
  };

  const openEmailModal = () => {
    setEmailRecipients([]);
    setEmailInput('');
    setEmailResult(null);
    setEmailModalVisible(true);
  };

  const addEmailRecipient = () => {
    const email = emailInput.trim();
    if (email && !emailRecipients.includes(email)) {
      setEmailRecipients([...emailRecipients, email]);
    }
    setEmailInput('');
  };

  const handleSendEmail = async () => {
    if (!selectedTemplate || !previewData || emailRecipients.length === 0) return;
    setEmailing(true);
    setEmailResult(null);
    try {
      const res = await reports.emailReport({
        dataset: selectedTemplate.value,
        columns: selectedColumns.map((c) => c.value),
        filters: buildFilters(),
        recipients: emailRecipients,
        html_body: buildEmailHtml(),
      });
      const sent = res.data.results.filter((r) => r.sent).length;
      const failed = res.data.results.filter((r) => !r.sent).length;
      if (failed === 0) {
        setEmailResult(`Sent to ${sent} recipient${sent > 1 ? 's' : ''}.`);
      } else {
        setEmailResult(`Sent: ${sent}, Failed: ${failed}`);
      }
    } catch {
      setEmailResult('Failed to send email.');
    } finally {
      setEmailing(false);
    }
  };

  // ─── Filters ────────────────────────────────────────────────────────────────

  const handleExportAmortization = async () => {
    if (!selectedAmortizationLease) return;
    setExportingAmortization(true);
    setAccountingExportError(null);
    try {
      const res = await reports.exportAmortizationCsv(selectedAmortizationLease.value);
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `amortization_${selectedAmortizationLease.label.replace(/[^a-zA-Z0-9_-]/g, '_')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setAccountingExportError('Failed to export amortization schedule.');
    } finally {
      setExportingAmortization(false);
    }
  };

  const handleExportMaturity = async () => {
    setExportingMaturity(true);
    setAccountingExportError(null);
    try {
      const res = await reports.exportMaturityCsv();
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `maturity_analysis_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setAccountingExportError('Failed to export maturity analysis.');
    } finally {
      setExportingMaturity(false);
    }
  };

  const handleExportRentRoll = async () => {
    setExportingRentRoll(true);
    setAccountingExportError(null);
    try {
      const res = await leasesApi.rentRoll();
      const { rows, total_monthly, total_annual } = res.data;
      const headers = ['Lease Name', 'Office', 'Lessor', 'Monthly Rent', 'Annual Rent', 'Escalation %', 'Expiration', 'Days Remaining', 'Classification', 'Currency', 'Manager'];
      const csvRows = rows.map((r: RentRollRow) => [
        r.lease_name,
        r.office_name ?? '',
        r.lessor_name ?? '',
        r.monthly_rent,
        r.annual_rent,
        r.annual_escalation_rate != null ? `${(r.annual_escalation_rate * 100).toFixed(2)}%` : '',
        r.lease_expiration ?? '',
        r.days_to_expiration ?? '',
        r.lease_classification ?? '',
        r.currency,
        r.manager_name ?? '',
      ]);
      csvRows.push(['TOTALS', '', '', total_monthly, total_annual, '', '', '', '', '', '']);
      const content = [headers, ...csvRows]
        .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
        .join('\n');
      const url = URL.createObjectURL(new Blob([content], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `rent_roll_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setAccountingExportError('Failed to export rent roll.');
    } finally {
      setExportingRentRoll(false);
    }
  };

  const setFilter = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const renderFilterControl = (fc: FilterConfig) => {
    const value = filters[fc.key] ?? '';

    if (fc.type === 'boolean') {
      const selected = value
        ? { value, label: value === 'true' ? 'Yes' : 'No' }
        : ALL_OPTION;
      return (
        <FormField label={fc.label} key={fc.key}>
          <Select
            selectedOption={selected}
            onChange={({ detail }) => setFilter(fc.key, detail.selectedOption.value ?? '')}
            options={[ALL_OPTION, { value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]}
          />
        </FormField>
      );
    }

    if (fc.type === 'select' && fc.options) {
      const selected = value
        ? { value, label: fc.options.find((o) => o.value === value)?.label ?? value }
        : ALL_OPTION;
      return (
        <FormField label={fc.label} key={fc.key}>
          <Select
            selectedOption={selected}
            onChange={({ detail }) => setFilter(fc.key, detail.selectedOption.value ?? '')}
            options={[ALL_OPTION, ...fc.options]}
          />
        </FormField>
      );
    }

    return (
      <FormField label={fc.label} description={value ? undefined : 'Leave empty for all'} key={fc.key}>
        <Input
          value={value}
          type={fc.type === 'number' ? 'number' : 'text'}
          onChange={({ detail }) => setFilter(fc.key, detail.value)}
          placeholder="All"
        />
      </FormField>
    );
  };

  const canAct = !!selectedTemplate && selectedColumns.length > 0;

  const previewColumnDefs = previewData
    ? previewData.headers.map((header, idx) => ({
        id: previewData.headerKeys[idx],
        header,
        cell: (item: PreviewRow) => {
          const val = item[previewData.headerKeys[idx]];
          return val === null || val === undefined || val === '' ? '—' : String(val);
        },
        sortingField: previewData.headerKeys[idx],
      }))
    : [];

  return (
    <ContentLayout
      header={
        <Header variant="h1" description="Select a dataset, apply filters, preview data, then download or print.">
          Reports
        </Header>
      }
    >
      <SpaceBetween size="l">
        {(templateError || error) && (
          <Alert type="error" dismissible onDismiss={() => { setTemplateError(null); setError(null); }}>
            {templateError || error}
          </Alert>
        )}

        {/* AI-generated operations briefing (Pro+) */}
        <AISummaryPanel />

        {/* Quick Export */}
        <Container
          header={
            <Header variant="h2" description="One-click downloads of the most common financial exports.">
              Quick Export
            </Header>
          }
        >
          <SpaceBetween direction="horizontal" size="s">
            <Button iconName="download" loading={exportingRentRoll} onClick={handleExportRentRoll}>
              Rent Roll (CSV)
            </Button>
            <Button
              iconName="download"
              loading={exportingMaturity}
              disabled={portfolioLoading || (portfolio?.leases.length ?? 0) === 0}
              onClick={handleExportMaturity}
            >
              Portfolio Maturity (CSV)
            </Button>
          </SpaceBetween>
          {accountingExportError && (
            <Box padding={{ top: 's' }}>
              <Alert type="error">{accountingExportError}</Alert>
            </Box>
          )}
        </Container>

        {/* Configuration */}
        <Container header={<Header variant="h2">Report Configuration</Header>}>
          <SpaceBetween size="l">
            <ColumnLayout columns={2}>
              <FormField label="Dataset" stretch>
                <Select
                  selectedOption={selectedTemplate}
                  onChange={({ detail }) => handleTemplateChange(detail.selectedOption as SelectOption | null)}
                  options={templateOptions}
                  placeholder="Choose a dataset"
                  statusType={loadingTemplates ? 'loading' : 'finished'}
                  loadingText="Loading..."
                  filteringType="auto"
                />
              </FormField>

              <FormField label="Columns" description="Select columns to include." stretch>
                <Multiselect
                  selectedOptions={selectedColumns}
                  onChange={({ detail }) => setSelectedColumns(detail.selectedOptions as SelectOption[])}
                  options={columnOptions}
                  placeholder="Choose columns"
                  filteringType="auto"
                  deselectAriaLabel={(option) => `Remove ${option.label}`}
                  tokenLimit={6}
                  disabled={!activeTemplate}
                />
              </FormField>
            </ColumnLayout>

            {filtersConfig.length > 0 && (
              <>
                <Header variant="h3">Filters</Header>
                <ColumnLayout columns={filtersConfig.length >= 3 ? 3 : filtersConfig.length}>
                  {filtersConfig.map(renderFilterControl)}
                </ColumnLayout>
              </>
            )}

            <ColumnLayout columns={2}>
              <FormField label="Download Format">
                <RadioGroup
                  value={format}
                  onChange={({ detail }) => setFormat(detail.value as Format)}
                  items={[
                    { value: 'pdf', label: 'PDF' },
                    { value: 'csv', label: 'CSV' },
                    { value: 'xlsx', label: 'Excel (XLSX)' },
                  ]}
                />
              </FormField>

              <FormField label="Actions">
                <SpaceBetween direction="horizontal" size="xs">
                  <Button
                    onClick={handlePreview}
                    disabled={!canAct}
                    loading={previewing}
                    loadingText="Loading..."
                    iconName="search"
                  >
                    Preview
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleGenerate}
                    disabled={!canAct}
                    loading={generating}
                    loadingText="Generating..."
                    iconName="download"
                  >
                    Download
                  </Button>
                  {previewData && (
                    <Button onClick={handlePrint} iconName="file">
                      Print
                    </Button>
                  )}
                </SpaceBetween>
              </FormField>
            </ColumnLayout>
          </SpaceBetween>
        </Container>

        {/* Preview Table */}
        {previewData && (
          <Table
            columnDefinitions={previewColumnDefs}
            items={previewData.rows}
            trackBy="_idx"
            header={
              <Header
                counter={`(${previewData.total})`}
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={handlePrint} iconName="file">Print</Button>
                    <Button onClick={openEmailModal} iconName="envelope">Email</Button>
                    <Button variant="primary" onClick={handleGenerate} loading={generating} iconName="download">
                      Download {format.toUpperCase()}
                    </Button>
                  </SpaceBetween>
                }
              >
                {previewData.title}
              </Header>
            }
            stickyHeader
            stripedRows
            wrapLines
            empty={
              <Box textAlign="center" color="inherit" padding="l">
                <b>No records found.</b>
                <Box variant="p">Try adjusting your filters.</Box>
              </Box>
            }
          />
        )}

        {!previewData && activeTemplate && !previewing && (
          <Box textAlign="center" color="text-body-secondary" padding="l">
            Click <strong>Preview</strong> to see your report data before downloading.
          </Box>
        )}

        {/* Email Modal */}
        <Modal
          visible={emailModalVisible}
          onDismiss={() => setEmailModalVisible(false)}
          header="Email Report"
          footer={
            <Box float="right">
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => setEmailModalVisible(false)}>Cancel</Button>
                <Button
                  variant="primary"
                  loading={emailing}
                  disabled={emailRecipients.length === 0}
                  onClick={handleSendEmail}
                >
                  Send
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="l">
            <Box variant="p">
              Send <strong>{previewData?.title}</strong> as an HTML email with a PDF attachment to the recipients below.
            </Box>

            <FormField label="Recipients" description="Press Enter or click Add for each email address.">
              <SpaceBetween size="xs">
                <SpaceBetween direction="horizontal" size="xs">
                  <Input
                    value={emailInput}
                    onChange={({ detail }) => setEmailInput(detail.value)}
                    onKeyDown={({ detail }) => {
                      if (detail.key === 'Enter') addEmailRecipient();
                    }}
                    placeholder="email@example.com"
                  />
                  <Button onClick={addEmailRecipient}>Add</Button>
                </SpaceBetween>
                {emailRecipients.length > 0 && (
                  <TokenGroup
                    items={emailRecipients.map((e) => ({ label: e }))}
                    onDismiss={({ detail }) => {
                      setEmailRecipients(emailRecipients.filter((_, i) => i !== detail.itemIndex));
                    }}
                  />
                )}
              </SpaceBetween>
            </FormField>

            {emailResult && (
              <StatusIndicator type={emailResult.includes('Failed') ? 'error' : 'success'}>
                {emailResult}
              </StatusIndicator>
            )}
          </SpaceBetween>
        </Modal>

        {/* Lease Accounting Portfolio */}
        <Container header={<Header variant="h2">Lease Accounting Portfolio (ASC 842 / IFRS 16)</Header>}>
          {portfolioLoading && (
            <Box textAlign="center" padding="l"><Spinner size="normal" /></Box>
          )}
          {portfolioError && (
            <Alert type="error">{portfolioError}</Alert>
          )}
          {portfolio && !portfolioLoading && (
            <SpaceBetween size="l">
              <ColumnLayout columns={5} variant="text-grid">
                <div>
                  <Box variant="awsui-key-label">Total ROU Assets</Box>
                  <Box>{formatCurrency(portfolio.total_rou)}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Current Lease Liability</Box>
                  <Box>{formatCurrency(portfolio.total_current_liability)}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Non-Current Lease Liability</Box>
                  <Box>{formatCurrency(portfolio.total_noncurrent_liability)}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Wtd Avg IBR</Box>
                  <Box>{formatPct(portfolio.weighted_avg_ibr)}</Box>
                </div>
                <div>
                  <Box variant="awsui-key-label">Wtd Avg Remaining Term</Box>
                  <Box>{portfolio.weighted_avg_remaining_months != null ? `${portfolio.weighted_avg_remaining_months.toFixed(1)} months` : '—'}</Box>
                </div>
              </ColumnLayout>
              <Table
                columnDefinitions={[
                  { id: 'lease_name', header: 'Lease Name', cell: (item) => item.lease_name },
                  { id: 'office_name', header: 'Office', cell: (item) => item.office_name ?? '—' },
                  { id: 'accounting_standard', header: 'Standard', cell: (item) => item.accounting_standard.toUpperCase() },
                  { id: 'lease_classification', header: 'Classification', cell: (item) => item.lease_classification.charAt(0).toUpperCase() + item.lease_classification.slice(1) },
                  { id: 'initial_rou_asset', header: 'Initial ROU Asset', cell: (item) => formatCurrency(item.initial_rou_asset, item.currency) },
                  { id: 'initial_lease_liability', header: 'Initial Liability', cell: (item) => formatCurrency(item.initial_lease_liability, item.currency) },
                  { id: 'remaining_rou', header: 'Remaining ROU', cell: (item) => formatCurrency(item.remaining_rou, item.currency) },
                  { id: 'remaining_liability', header: 'Remaining Liability', cell: (item) => formatCurrency(item.remaining_liability, item.currency) },
                  { id: 'ibr_annual', header: 'IBR', cell: (item) => formatPct(item.ibr_annual) },
                  { id: 'remaining_months', header: 'Remaining Term', cell: (item) => `${item.remaining_months} mo` },
                ]}
                items={portfolio.leases}
                stripedRows
                empty={
                  <Box textAlign="center" color="inherit" padding="m">
                    No leases with accounting data. Add accounting fields to leases to see them here.
                  </Box>
                }
              />
            </SpaceBetween>
          )}
        </Container>

        {/* Accounting Reports */}
        <Container header={<Header variant="h2">Accounting Reports</Header>}>
          <SpaceBetween size="l">
            {accountingExportError && <Alert type="error">{accountingExportError}</Alert>}

            {/* Amortization Schedule Export */}
            <SpaceBetween size="s">
              <Box variant="h3">Amortization Schedule</Box>
              <Box variant="p" color="text-body-secondary">
                Export the full month-by-month amortization schedule (opening/closing liability, interest, principal, ROU carrying value) for a single lease as CSV.
              </Box>
              <SpaceBetween direction="horizontal" size="m">
                <FormField label="Lease">
                  <Select
                    selectedOption={selectedAmortizationLease}
                    onChange={({ detail }) =>
                      setSelectedAmortizationLease(
                        detail.selectedOption.value
                          ? (detail.selectedOption as SelectOption)
                          : null
                      )
                    }
                    options={[
                      { value: '', label: 'Select a lease…' },
                      ...(portfolio?.leases ?? []).map((l) => ({
                        value: l.lease_id,
                        label: l.lease_name + (l.office_name ? ` (${l.office_name})` : ''),
                      })),
                    ]}
                    placeholder="Select a lease…"
                    disabled={portfolioLoading || !portfolio}
                  />
                </FormField>
                <FormField label="&nbsp;">
                  <Button
                    iconName="download"
                    loading={exportingAmortization}
                    disabled={!selectedAmortizationLease}
                    onClick={handleExportAmortization}
                  >
                    Export CSV
                  </Button>
                </FormField>
              </SpaceBetween>
            </SpaceBetween>

            {/* Maturity Analysis Export */}
            <SpaceBetween size="s">
              <Box variant="h3">Maturity Analysis (Portfolio)</Box>
              <Box variant="p" color="text-body-secondary">
                Export the ASC 842 / IFRS 16 maturity disclosure for all leases — Year 1 through Thereafter buckets, total undiscounted obligations, imputed interest, and present value. Suitable for financial statement footnote disclosures.
              </Box>
              <Button
                iconName="download"
                loading={exportingMaturity}
                disabled={portfolioLoading || (portfolio?.leases.length ?? 0) === 0}
                onClick={handleExportMaturity}
              >
                Export Portfolio Maturity CSV
              </Button>
            </SpaceBetween>
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default ReportsPage;
