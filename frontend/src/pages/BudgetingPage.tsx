import React, { useCallback, useEffect, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Modal from '@cloudscape-design/components/modal';
import EntityFormModal from '@/components/common/EntityFormModal';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { budgets as budgetsApi, gl as glApi } from '@/api';
import type { Budget, BudgetReport, GLAccount } from '@/types';

const fmt = (v: number | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const pct = (v: number | null | undefined) => (v != null ? `${v.toFixed(1)}%` : '—');

interface LineDraft { account_id: string; amount: string; }

const statusBadge = (s: string) => {
  const color = s === 'active' ? 'green' : s === 'archived' ? 'grey' : 'blue';
  return <Badge color={color as 'green' | 'grey' | 'blue'}>{s}</Badge>;
};

const BudgetingPage: React.FC = () => {
  const { addFlash } = useFlashbar();

  const [items, setItems] = useState<Budget[]>([]);
  const [accounts, setAccounts] = useState<GLAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<BudgetReport | null>(null);

  // Create/edit modal
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [fiscalYear, setFiscalYear] = useState(String(new Date().getFullYear()));
  const [lines, setLines] = useState<LineDraft[]>([{ account_id: '', amount: '' }]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, a] = await Promise.all([budgetsApi.list(), glApi.listAccounts()]);
      setItems(b.data);
      setAccounts(a.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load budgets.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    void load();
  }, [load]);

  const accountOptions = accounts.map((a) => ({
    label: `${a.code} — ${a.name}`,
    value: a.id,
  }));

  const openCreate = () => {
    setEditingId(null);
    setName('');
    setFiscalYear(String(new Date().getFullYear()));
    setLines([{ account_id: '', amount: '' }]);
    setModalOpen(true);
  };

  const openEdit = (b: Budget) => {
    setEditingId(b.id);
    setName(b.name);
    setFiscalYear(String(b.fiscal_year));
    setLines(
      b.lines.length
        ? b.lines.map((l) => ({ account_id: l.account_id, amount: String(l.amount) }))
        : [{ account_id: '', amount: '' }],
    );
    setModalOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const payloadLines = lines
        .filter((l) => l.account_id && l.amount !== '')
        .map((l) => ({ account_id: l.account_id, amount: l.amount }));
      const payload = {
        name,
        fiscal_year: Number(fiscalYear),
        lines: payloadLines,
      };
      if (editingId) {
        await budgetsApi.update(editingId, payload);
      } else {
        await budgetsApi.create(payload);
      }
      setModalOpen(false);
      await load();
      addFlash({ type: 'success', content: 'Budget saved.' });
    } catch {
      addFlash({ type: 'error', content: 'Failed to save budget.' });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (b: Budget) => {
    try {
      await budgetsApi.remove(b.id);
      await load();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete budget.' });
    }
  };

  const openReport = async (b: Budget) => {
    try {
      const resp = await budgetsApi.report(b.id);
      setReport(resp.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load variance report.' });
    }
  };

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="GL-account-level annual budgets with budget-vs-actual variance"
          actions={<Button variant="primary" onClick={openCreate}>New budget</Button>}
        >
          Budgeting
        </Header>
      }
    >
      <Table<Budget>
        loading={loading}
        items={items}
        variant="container"
        header={<Header counter={`(${items.length})`}>Budgets</Header>}
        empty={<Box textAlign="center" padding="l">No budgets yet.</Box>}
        columnDefinitions={[
          { id: 'name', header: 'Name', cell: (b) => b.name },
          { id: 'year', header: 'Fiscal year', cell: (b) => b.fiscal_year },
          { id: 'status', header: 'Status', cell: (b) => statusBadge(b.status) },
          { id: 'total', header: 'Total budget', cell: (b) => fmt(b.total_amount) },
          { id: 'lines', header: 'Accounts', cell: (b) => b.lines.length },
          {
            id: 'actions',
            header: '',
            cell: (b) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => openReport(b)}>Variance</Button>
                <Button variant="inline-link" onClick={() => openEdit(b)}>Edit</Button>
                <Button variant="inline-link" onClick={() => remove(b)}>Delete</Button>
              </SpaceBetween>
            ),
          },
        ]}
      />

      {/* Create / edit modal */}
      <EntityFormModal
        visible={modalOpen}
        title={editingId ? 'Edit budget' : 'New budget'}
        onCancel={() => setModalOpen(false)}
        onSubmit={save}
        submitting={saving}
        submitLabel="Save"
        size="large"
      >
        <SpaceBetween size="m">
          <ColumnLayout columns={2}>
            <FormField label="Name">
              <Input value={name} onChange={(e) => setName(e.detail.value)} />
            </FormField>
            <FormField label="Fiscal year">
              <Input type="number" value={fiscalYear} onChange={(e) => setFiscalYear(e.detail.value)} />
            </FormField>
          </ColumnLayout>
          <FormField label="Account lines">
            <SpaceBetween size="xs">
              {lines.map((line, idx) => (
                <ColumnLayout columns={2} key={idx}>
                  <Select
                    selectedOption={accountOptions.find((o) => o.value === line.account_id) ?? null}
                    onChange={(e) => {
                      const next = [...lines];
                      next[idx] = { ...next[idx], account_id: e.detail.selectedOption.value ?? '' };
                      setLines(next);
                    }}
                    options={accountOptions}
                    placeholder="Select account"
                    filteringType="auto"
                  />
                  <SpaceBetween direction="horizontal" size="xs">
                    <Input
                      type="number"
                      value={line.amount}
                      placeholder="Amount"
                      onChange={(e) => {
                        const next = [...lines];
                        next[idx] = { ...next[idx], amount: e.detail.value };
                        setLines(next);
                      }}
                    />
                    <Button
                      iconName="close"
                      variant="icon"
                      onClick={() => setLines(lines.filter((_, i) => i !== idx))}
                    />
                  </SpaceBetween>
                </ColumnLayout>
              ))}
              <Button
                iconName="add-plus"
                onClick={() => setLines([...lines, { account_id: '', amount: '' }])}
              >
                Add line
              </Button>
            </SpaceBetween>
          </FormField>
        </SpaceBetween>
      </EntityFormModal>

      {/* Variance report modal */}
      <Modal
        visible={report !== null}
        onDismiss={() => setReport(null)}
        header={report ? `${report.name} — FY${report.fiscal_year} variance` : ''}
        size="max"
      >
        {report && (
          <SpaceBetween size="m">
            <ColumnLayout columns={3} variant="text-grid">
              <div><Box variant="awsui-key-label">Total budget</Box>{fmt(report.total_budget)}</div>
              <div><Box variant="awsui-key-label">Total actual</Box>{fmt(report.total_actual)}</div>
              <div><Box variant="awsui-key-label">Total variance</Box>{fmt(report.total_variance)}</div>
            </ColumnLayout>
            <Table<BudgetReport['rows'][number]>
              items={report.rows}
              columnDefinitions={[
                { id: 'code', header: 'Account', cell: (r) => `${r.code} — ${r.name}` },
                { id: 'budget', header: 'Budget', cell: (r) => fmt(r.budget) },
                { id: 'actual', header: 'Actual', cell: (r) => fmt(r.actual) },
                { id: 'variance', header: 'Variance', cell: (r) => fmt(r.variance) },
                { id: 'variance_pct', header: 'Variance %', cell: (r) => pct(r.variance_pct) },
              ]}
              empty={<Box textAlign="center" padding="l">No budget lines.</Box>}
            />
          </SpaceBetween>
        )}
      </Modal>
    </ContentLayout>
  );
};

export default BudgetingPage;
