import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Container from '@cloudscape-design/components/container';
import ContentLayout from '@cloudscape-design/components/content-layout';
import DatePicker from '@cloudscape-design/components/date-picker';
import FormField from '@cloudscape-design/components/form-field';
import Header from '@cloudscape-design/components/header';
import Input from '@cloudscape-design/components/input';
import Modal from '@cloudscape-design/components/modal';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Textarea from '@cloudscape-design/components/textarea';
import CreateWizardModal from '@/components/common/CreateWizardModal';
import EmptyState from '@/components/common/EmptyState';
import { procurement as procurementApi, vendors as vendorsApi, offices as officesApi } from '@/api';
import { useFlashbar } from '@/context/FlashbarContext';
import type { PurchaseRequisition, Vendor, Office } from '@/types';

/**
 * Procurement: request, compete, approve, order, receive.
 *
 * The page is organised around the state a request is actually in rather than
 * as a CRUD table, because the control only holds if the next action is
 * obvious. Each selected requisition shows exactly one primary action, and the
 * bidding rules are explained where they bite instead of appearing as a
 * validation error after the fact.
 */

const fmt = (v: number | string | null | undefined) =>
  v != null
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const today = () => new Date().toISOString().slice(0, 10);

interface LineDraft {
  description: string;
  quantity: string;
  unit_price: string;
}

const emptyLine = (): LineDraft => ({ description: '', quantity: '1', unit_price: '' });

const statusBadge = (status: string) => {
  const color =
    status === 'approved' || status === 'ordered'
      ? 'green'
      : status === 'rejected'
        ? 'red'
        : status === 'submitted'
          ? 'blue'
          : 'grey';
  return <Badge color={color as 'green' | 'red' | 'blue' | 'grey'}>{status}</Badge>;
};

const ProcurementPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [requisitions, setRequisitions] = useState<PurchaseRequisition[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [selected, setSelected] = useState<PurchaseRequisition | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  // Create wizard state
  const [wizardOpen, setWizardOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [officeId, setOfficeId] = useState('');
  const [category, setCategory] = useState('');
  const [neededBy, setNeededBy] = useState('');
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);

  // Quote modal state
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [quoteVendorId, setQuoteVendorId] = useState('');
  const [quoteAmount, setQuoteAmount] = useState('');
  const [quoteReference, setQuoteReference] = useState('');
  const [savingQuote, setSavingQuote] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reqRes, vendorRes, officeRes] = await Promise.all([
        procurementApi.listRequisitions(),
        vendorsApi.list({ page_size: 500 }),
        officesApi.list({ page_size: 500 }),
      ]);
      setRequisitions(reqRes.data);
      setVendors(vendorRes.data.items ?? []);
      setOffices(officeRes.data.items ?? []);
      setSelected((prev) =>
        prev ? reqRes.data.find((r) => r.id === prev.id) ?? null : null,
      );
    } catch {
      addFlash({ type: 'error', content: 'Could not load procurement data.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    load();
  }, [load]);

  const vendorName = useCallback(
    (id: string) => vendors.find((v) => v.id === id)?.company_name ?? 'Unknown vendor',
    [vendors],
  );

  const estimatedTotal = useMemo(
    () =>
      lines.reduce(
        (sum, l) => sum + (parseFloat(l.quantity) || 0) * (parseFloat(l.unit_price) || 0),
        0,
      ),
    [lines],
  );

  const resetWizard = () => {
    setTitle('');
    setDescription('');
    setOfficeId('');
    setCategory('');
    setNeededBy('');
    setLines([emptyLine()]);
  };

  const runAction = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      addFlash({ type: 'success', content: label });
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Action failed.' });
    } finally {
      setBusy(false);
    }
  };

  const createRequisition = async () => {
    setSaving(true);
    try {
      const res = await procurementApi.createRequisition({
        title: title.trim(),
        description: description.trim() || null,
        office_id: officeId || null,
        category: category.trim() || null,
        needed_by: neededBy || null,
        lines: lines
          .filter((l) => l.description.trim())
          .map((l) => ({
            description: l.description.trim(),
            quantity: parseFloat(l.quantity) || 1,
            unit_price: parseFloat(l.unit_price) || 0,
          })),
      });
      addFlash({ type: 'success', content: 'Requisition created as a draft.' });
      setWizardOpen(false);
      resetWizard();
      await load();
      setSelected(res.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Could not create the requisition.' });
    } finally {
      setSaving(false);
    }
  };

  const addQuote = async () => {
    if (!selected) return;
    setSavingQuote(true);
    try {
      await procurementApi.addQuote(selected.id, {
        vendor_id: quoteVendorId,
        amount: parseFloat(quoteAmount) || 0,
        quote_date: today(),
        reference: quoteReference.trim() || null,
      });
      setQuoteOpen(false);
      setQuoteVendorId('');
      setQuoteAmount('');
      setQuoteReference('');
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      addFlash({ type: 'error', content: detail || 'Could not record the quote.' });
    } finally {
      setSavingQuote(false);
    }
  };

  // The single most useful thing the page can say: what happens next.
  const nextStep = (req: PurchaseRequisition): { text: string; action?: React.ReactNode } => {
    if (req.status === 'ordered') {
      return { text: 'Ordered. Record receipts as goods or services arrive.' };
    }
    if (req.status === 'rejected') {
      return {
        text: `Returned for changes${req.rejection_reason ? `: ${req.rejection_reason}` : ''}. Edit and resubmit.`,
        action: (
          <Button loading={busy} onClick={() => runAction('Resubmitted for approval.', () => procurementApi.submitRequisition(req.id))}>
            Resubmit
          </Button>
        ),
      };
    }
    if (req.approval_status === 'pending' && req.status === 'submitted') {
      return {
        text: 'Waiting for a second approver. You cannot approve a request you submitted.',
        action: (
          <SpaceBetween direction="horizontal" size="xs">
            <Button
              loading={busy}
              onClick={() => {
                const reason = window.prompt('Why is this being returned?') ?? undefined;
                runAction('Returned to the requester.', () => procurementApi.rejectRequisition(req.id, reason));
              }}
            >
              Return
            </Button>
            <Button
              variant="primary"
              loading={busy}
              onClick={() => runAction('Requisition approved.', () => procurementApi.approveRequisition(req.id))}
            >
              Approve
            </Button>
          </SpaceBetween>
        ),
      };
    }
    if (req.status === 'approved') {
      return {
        text: 'Approved. Issue the purchase order to commit the spend.',
        action: (
          <Button
            variant="primary"
            loading={busy}
            onClick={() =>
              runAction('Purchase order issued.', () =>
                procurementApi.issuePurchaseOrder(req.id, { order_date: today() }),
              )
            }
          >
            Issue purchase order
          </Button>
        ),
      };
    }
    return {
      text: 'Draft. Add competing quotes, then submit for approval.',
      action: (
        <Button
          variant="primary"
          loading={busy}
          onClick={() => runAction('Submitted for approval.', () => procurementApi.submitRequisition(req.id))}
        >
          Submit for approval
        </Button>
      ),
    };
  };

  const detail = selected && (
    <SpaceBetween size="l">
      <Container
        header={
          <Header
            variant="h2"
            description={selected.description ?? undefined}
            actions={nextStep(selected).action}
          >
            {selected.title}
          </Header>
        }
      >
        <SpaceBetween size="m">
          <Alert type={selected.status === 'rejected' ? 'warning' : 'info'}>
            {nextStep(selected).text}
          </Alert>
          <ColumnLayout columns={4} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Status</Box>
              {statusBadge(selected.status)}
            </div>
            <div>
              <Box variant="awsui-key-label">Estimated total</Box>
              {fmt(selected.estimated_total)}
            </div>
            <div>
              <Box variant="awsui-key-label">Needed by</Box>
              {selected.needed_by ?? '—'}
            </div>
            <div>
              <Box variant="awsui-key-label">Category</Box>
              {selected.category ?? '—'}
            </div>
          </ColumnLayout>
        </SpaceBetween>
      </Container>

      <Table
        items={selected.lines}
        header={<Header variant="h3" counter={`(${selected.lines.length})`}>Items requested</Header>}
        columnDefinitions={[
          { id: 'description', header: 'Description', cell: (l) => l.description },
          { id: 'qty', header: 'Qty', cell: (l) => l.quantity },
          { id: 'unit', header: 'Unit price', cell: (l) => fmt(l.unit_price) },
          { id: 'amount', header: 'Amount', cell: (l) => fmt(l.amount) },
        ]}
        empty={<Box textAlign="center">No items.</Box>}
      />

      <Table
        items={selected.quotes}
        header={
          <Header
            variant="h3"
            counter={`(${selected.quotes.length})`}
            description="Record what each vendor bid. The winner must be selected before an order can be issued, and choosing a higher bid requires a written reason."
            actions={
              selected.status !== 'ordered' && (
                <Button onClick={() => setQuoteOpen(true)}>Add quote</Button>
              )
            }
          >
            Competing bids
          </Header>
        }
        columnDefinitions={[
          { id: 'vendor', header: 'Vendor', cell: (q) => vendorName(q.vendor_id) },
          { id: 'amount', header: 'Amount', cell: (q) => fmt(q.amount) },
          { id: 'reference', header: 'Reference', cell: (q) => q.reference ?? '—' },
          {
            id: 'selected',
            header: 'Selected',
            cell: (q) =>
              q.is_selected ? <Badge color="green">Winner</Badge> : <Box color="text-body-secondary">—</Box>,
          },
          {
            id: 'actions',
            header: '',
            cell: (q) =>
              !q.is_selected && selected.status !== 'ordered' ? (
                <Button
                  variant="inline-link"
                  loading={busy}
                  onClick={() => {
                    const cheapest = Math.min(...selected.quotes.map((x) => Number(x.amount)));
                    const reason =
                      Number(q.amount) > cheapest
                        ? window.prompt(
                            'This is not the lowest bid. Record why it was selected:',
                          ) ?? ''
                        : undefined;
                    runAction('Winning bid selected.', () =>
                      procurementApi.selectQuote(q.id, reason || undefined),
                    );
                  }}
                >
                  Select
                </Button>
              ) : null,
          },
        ]}
        empty={
          <EmptyState
            title="No competing bids recorded"
            description="Above your organization's bid threshold, an order cannot be issued without them."
            actionLabel="Add the first quote"
            onAction={() => setQuoteOpen(true)}
          />
        }
      />
    </SpaceBetween>
  );

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Request spend, compare bids, get approval, then commit a purchase order."
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button iconName="refresh" onClick={load} loading={loading} />
              <Button variant="primary" onClick={() => setWizardOpen(true)}>
                New request
              </Button>
            </SpaceBetween>
          }
        >
          Procurement
        </Header>
      }
    >
      <SpaceBetween size="l">
        <Table
          loading={loading}
          items={requisitions}
          selectionType="single"
          selectedItems={selected ? [selected] : []}
          onSelectionChange={({ detail: d }) => setSelected(d.selectedItems[0] ?? null)}
          trackBy="id"
          columnDefinitions={[
            { id: 'title', header: 'Request', cell: (r) => r.title },
            { id: 'number', header: 'Number', cell: (r) => r.requisition_number ?? '—' },
            { id: 'total', header: 'Estimated', cell: (r) => fmt(r.estimated_total) },
            { id: 'bids', header: 'Bids', cell: (r) => r.quotes.length },
            { id: 'needed', header: 'Needed by', cell: (r) => r.needed_by ?? '—' },
            { id: 'status', header: 'Status', cell: (r) => statusBadge(r.status) },
          ]}
          empty={
            <EmptyState
              title="No purchase requests yet"
              description="Raising a request first is what lets you compare bids and prove the spend was approved."
              actionLabel="Create the first request"
              onAction={() => setWizardOpen(true)}
            />
          }
        />

        {detail}
      </SpaceBetween>

      <CreateWizardModal
        visible={wizardOpen}
        entityLabel="purchase request"
        size="large"
        submitting={saving}
        dirty={Boolean(title || description || lines.some((l) => l.description))}
        onCancel={() => {
          setWizardOpen(false);
          resetWizard();
        }}
        onSubmit={createRequisition}
        steps={[
          {
            title: 'What do you need?',
            description: 'Describe the work or goods and where they are needed.',
            content: (
              <SpaceBetween size="m">
                <FormField label="Title" description="A short summary someone approving this will recognise.">
                  <Input
                    value={title}
                    onChange={({ detail: d }) => setTitle(d.value)}
                    placeholder="Replace rooftop HVAC unit RTU-3"
                  />
                </FormField>
                <FormField label="Why is it needed?" description="Context for the approver.">
                  <Textarea
                    rows={3}
                    value={description}
                    onChange={({ detail: d }) => setDescription(d.value)}
                  />
                </FormField>
                <ColumnLayout columns={3}>
                  <FormField label="Property">
                    <Select
                      selectedOption={
                        officeId
                          ? {
                              value: officeId,
                              label: offices.find((o) => o.id === officeId)?.location_name ?? '',
                            }
                          : null
                      }
                      options={offices.map((o) => ({ value: o.id, label: o.location_name }))}
                      onChange={({ detail: d }) => setOfficeId(d.selectedOption.value ?? '')}
                      filteringType="auto"
                      placeholder="Select a property"
                      empty="No properties"
                    />
                  </FormField>
                  <FormField label="Category">
                    <Input
                      value={category}
                      onChange={({ detail: d }) => setCategory(d.value)}
                      placeholder="HVAC"
                    />
                  </FormField>
                  <FormField label="Needed by">
                    <DatePicker
                      value={neededBy}
                      onChange={({ detail: d }) => setNeededBy(d.value)}
                      placeholder="YYYY/MM/DD"
                    />
                  </FormField>
                </ColumnLayout>
              </SpaceBetween>
            ),
            validate: () => (!title.trim() ? 'Give the request a title.' : null),
          },
          {
            title: 'What will it cost?',
            description: 'Estimated cost decides whether competing bids and approval are required.',
            content: (
              <SpaceBetween size="m">
                {lines.map((line, idx) => (
                  <ColumnLayout key={idx} columns={4}>
                    <Input
                      value={line.description}
                      placeholder="Item or service"
                      onChange={({ detail: d }) =>
                        setLines((prev) =>
                          prev.map((l, i) => (i === idx ? { ...l, description: d.value } : l)),
                        )
                      }
                    />
                    <Input
                      type="number"
                      value={line.quantity}
                      placeholder="Qty"
                      onChange={({ detail: d }) =>
                        setLines((prev) =>
                          prev.map((l, i) => (i === idx ? { ...l, quantity: d.value } : l)),
                        )
                      }
                    />
                    <Input
                      type="number"
                      value={line.unit_price}
                      placeholder="Unit price"
                      onChange={({ detail: d }) =>
                        setLines((prev) =>
                          prev.map((l, i) => (i === idx ? { ...l, unit_price: d.value } : l)),
                        )
                      }
                    />
                    {lines.length > 1 && (
                      <Button
                        iconName="remove"
                        variant="icon"
                        ariaLabel="Remove line"
                        onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))}
                      />
                    )}
                  </ColumnLayout>
                ))}
                <Button iconName="add-plus" onClick={() => setLines((prev) => [...prev, emptyLine()])}>
                  Add item
                </Button>
                <Box textAlign="right" fontWeight="bold">
                  Estimated total: {fmt(estimatedTotal)}
                </Box>
              </SpaceBetween>
            ),
            validate: () =>
              lines.filter((l) => l.description.trim()).length === 0
                ? 'Add at least one item.'
                : null,
          },
          {
            title: 'Review',
            description: 'This is created as a draft. Add bids next, then submit for approval.',
            content: (
              <SpaceBetween size="m">
                <ColumnLayout columns={2} variant="text-grid">
                  <div>
                    <Box variant="awsui-key-label">Title</Box>
                    {title || '—'}
                  </div>
                  <div>
                    <Box variant="awsui-key-label">Estimated total</Box>
                    {fmt(estimatedTotal)}
                  </div>
                  <div>
                    <Box variant="awsui-key-label">Needed by</Box>
                    {neededBy || '—'}
                  </div>
                  <div>
                    <Box variant="awsui-key-label">Items</Box>
                    {lines.filter((l) => l.description.trim()).length}
                  </div>
                </ColumnLayout>
                <Alert type="info">
                  Nothing is committed yet. After approval you will issue a purchase order,
                  and the vendor's invoice will be matched against it before it can post.
                </Alert>
              </SpaceBetween>
            ),
          },
        ]}
      />

      <Modal
        visible={quoteOpen}
        onDismiss={() => setQuoteOpen(false)}
        header="Record a vendor quote"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setQuoteOpen(false)}>Cancel</Button>
              <Button
                variant="primary"
                loading={savingQuote}
                disabled={!quoteVendorId || !quoteAmount}
                onClick={addQuote}
              >
                Add quote
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Vendor">
            <Select
              selectedOption={
                quoteVendorId ? { value: quoteVendorId, label: vendorName(quoteVendorId) } : null
              }
              options={vendors.map((v) => ({ value: v.id, label: v.company_name }))}
              onChange={({ detail: d }) => setQuoteVendorId(d.selectedOption.value ?? '')}
              filteringType="auto"
              placeholder="Select a vendor"
              empty="No vendors"
            />
          </FormField>
          <FormField label="Quoted amount">
            <Input
              type="number"
              value={quoteAmount}
              onChange={({ detail: d }) => setQuoteAmount(d.value)}
            />
          </FormField>
          <FormField label="Quote reference" description="The vendor's own quote number, for the audit trail.">
            <Input
              value={quoteReference}
              onChange={({ detail: d }) => setQuoteReference(d.value)}
              placeholder="Q-5567"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
};

export default ProcurementPage;
