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
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useFlashbar } from '@/context/FlashbarContext';
import { owners as ownersApi } from '@/api';
import PortalInviteButton from '@/components/common/PortalInviteButton';
import type {
  PropertyOwner,
  OwnerStatus,
  OwnerLedgerEntry,
  LedgerEntryType,
  OwnerBalance,
  OwnerDistribution,
  DistributionMethod,
  TrustAccount,
  ComplianceStatus,
} from '@/types';

const fmtMoney = (v: string | null) =>
  v != null && v !== ''
    ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : '—';

const OWNER_STATUSES: OwnerStatus[] = ['active', 'inactive'];
const LEDGER_ENTRY_TYPES: LedgerEntryType[] = [
  'income',
  'expense',
  'management_fee',
  'distribution',
  'adjustment',
];
const DISTRIBUTION_METHODS: DistributionMethod[] = ['check', 'ach', 'wire', 'other'];
const COMPLIANCE_STATUSES: ComplianceStatus[] = [
  'pending',
  'under_review',
  'approved',
  'flagged',
];

const ownerBadge = (s: OwnerStatus) => (
  <Badge color={s === 'active' ? 'green' : 'grey'}>{s}</Badge>
);

const complianceBadge = (s: ComplianceStatus) => {
  const color = s === 'approved' ? 'green' : s === 'flagged' ? 'red' : 'blue';
  return <Badge color={color as 'green' | 'red' | 'blue'}>{s}</Badge>;
};

const OwnersPage: React.FC = () => {
  const { addFlash } = useFlashbar();
  const [ownersList, setOwnersList] = useState<PropertyOwner[]>([]);
  const [trustAccounts, setTrustAccounts] = useState<TrustAccount[]>([]);
  const [loading, setLoading] = useState(true);

  // Owner modal
  const [ownerOpen, setOwnerOpen] = useState(false);
  const [editing, setEditing] = useState<PropertyOwner | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [feePercent, setFeePercent] = useState('0');
  const [statusValue, setStatusValue] = useState<OwnerStatus>('active');
  const [notes, setNotes] = useState('');
  const [savingOwner, setSavingOwner] = useState(false);

  // Owner detail
  const [detailOwner, setDetailOwner] = useState<PropertyOwner | null>(null);
  const [balance, setBalance] = useState<OwnerBalance | null>(null);
  const [ledger, setLedger] = useState<OwnerLedgerEntry[]>([]);
  const [distributions, setDistributions] = useState<OwnerDistribution[]>([]);

  // Ledger entry modal
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [entryType, setEntryType] = useState<LedgerEntryType>('income');
  const [entryAmount, setEntryAmount] = useState('');
  const [entryDesc, setEntryDesc] = useState('');
  const [savingEntry, setSavingEntry] = useState(false);

  // Distribution modal
  const [distOpen, setDistOpen] = useState(false);
  const [distAmount, setDistAmount] = useState('');
  const [distMethod, setDistMethod] = useState<DistributionMethod>('ach');
  const [distMemo, setDistMemo] = useState('');
  const [savingDist, setSavingDist] = useState(false);

  // Trust account modal
  const [trustOpen, setTrustOpen] = useState(false);
  const [editingTrust, setEditingTrust] = useState<TrustAccount | null>(null);
  const [trustName, setTrustName] = useState('');
  const [trustBank, setTrustBank] = useState('');
  const [trustLast4, setTrustLast4] = useState('');
  const [savingTrust, setSavingTrust] = useState(false);

  const loadTop = useCallback(async () => {
    setLoading(true);
    try {
      const [o, t] = await Promise.all([
        ownersApi.list(),
        ownersApi.listTrustAccounts(),
      ]);
      setOwnersList(o.data);
      setTrustAccounts(t.data);
    } catch {
      addFlash({ type: 'error', content: 'Failed to load owners.' });
    } finally {
      setLoading(false);
    }
  }, [addFlash]);

  useEffect(() => {
    loadTop();
  }, [loadTop]);

  const loadDetail = useCallback(
    async (owner: PropertyOwner) => {
      try {
        const [b, l, d] = await Promise.all([
          ownersApi.balance(owner.id),
          ownersApi.listLedger(owner.id),
          ownersApi.listDistributions(owner.id),
        ]);
        setBalance(b.data);
        setLedger(l.data);
        setDistributions(d.data);
      } catch {
        addFlash({ type: 'error', content: 'Failed to load owner detail.' });
      }
    },
    [addFlash],
  );

  const openDetail = async (owner: PropertyOwner) => {
    setDetailOwner(owner);
    setBalance(null);
    setLedger([]);
    setDistributions([]);
    await loadDetail(owner);
  };

  const openOwnerCreate = () => {
    setEditing(null);
    setName('');
    setEmail('');
    setPhone('');
    setFeePercent('0');
    setStatusValue('active');
    setNotes('');
    setOwnerOpen(true);
  };

  const openOwnerEdit = (o: PropertyOwner) => {
    setEditing(o);
    setName(o.name);
    setEmail(o.email ?? '');
    setPhone(o.phone ?? '');
    setFeePercent(o.management_fee_percent);
    setStatusValue(o.status);
    setNotes(o.notes ?? '');
    setOwnerOpen(true);
  };

  const saveOwner = async () => {
    if (!name.trim()) {
      addFlash({ type: 'error', content: 'Owner name is required.' });
      return;
    }
    setSavingOwner(true);
    try {
      const payload = {
        name: name.trim(),
        email: email.trim() || null,
        phone: phone.trim() || null,
        management_fee_percent: feePercent.trim() || '0',
        status: statusValue,
        notes: notes.trim() || null,
      };
      if (editing) {
        await ownersApi.update(editing.id, payload);
        addFlash({ type: 'success', content: 'Owner updated.' });
      } else {
        await ownersApi.create(payload);
        addFlash({ type: 'success', content: 'Owner created.' });
      }
      setOwnerOpen(false);
      await loadTop();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save owner.' });
    } finally {
      setSavingOwner(false);
    }
  };

  const removeOwner = async (o: PropertyOwner) => {
    if (!window.confirm(`Delete owner ${o.name}?`)) return;
    try {
      await ownersApi.remove(o.id);
      addFlash({ type: 'success', content: 'Owner deleted.' });
      if (detailOwner?.id === o.id) setDetailOwner(null);
      await loadTop();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete owner.' });
    }
  };

  const saveEntry = async () => {
    if (!detailOwner || !entryAmount.trim()) {
      addFlash({ type: 'error', content: 'Amount is required.' });
      return;
    }
    setSavingEntry(true);
    try {
      await ownersApi.addLedgerEntry(detailOwner.id, {
        entry_type: entryType,
        amount: entryAmount.trim(),
        description: entryDesc.trim() || null,
      });
      addFlash({ type: 'success', content: 'Ledger entry posted.' });
      setLedgerOpen(false);
      setEntryAmount('');
      setEntryDesc('');
      await loadDetail(detailOwner);
    } catch {
      addFlash({ type: 'error', content: 'Failed to post entry.' });
    } finally {
      setSavingEntry(false);
    }
  };

  const saveDist = async () => {
    if (!detailOwner || !distAmount.trim()) {
      addFlash({ type: 'error', content: 'Amount is required.' });
      return;
    }
    setSavingDist(true);
    try {
      await ownersApi.createDistribution(detailOwner.id, {
        amount: distAmount.trim(),
        method: distMethod,
        memo: distMemo.trim() || null,
      });
      addFlash({ type: 'success', content: 'Distribution created.' });
      setDistOpen(false);
      setDistAmount('');
      setDistMemo('');
      await loadDetail(detailOwner);
    } catch {
      addFlash({ type: 'error', content: 'Failed to create distribution.' });
    } finally {
      setSavingDist(false);
    }
  };

  const payDist = async (d: OwnerDistribution) => {
    if (!detailOwner) return;
    try {
      await ownersApi.markDistributionPaid(detailOwner.id, d.id);
      addFlash({ type: 'success', content: 'Distribution marked paid.' });
      await loadDetail(detailOwner);
    } catch {
      addFlash({ type: 'error', content: 'Failed to mark paid.' });
    }
  };

  const voidDist = async (d: OwnerDistribution) => {
    if (!detailOwner) return;
    if (!window.confirm('Void this distribution?')) return;
    try {
      await ownersApi.voidDistribution(detailOwner.id, d.id);
      addFlash({ type: 'success', content: 'Distribution voided.' });
      await loadDetail(detailOwner);
    } catch {
      addFlash({ type: 'error', content: 'Failed to void distribution.' });
    }
  };

  const openTrustCreate = () => {
    setEditingTrust(null);
    setTrustName('');
    setTrustBank('');
    setTrustLast4('');
    setTrustOpen(true);
  };

  const openTrustEdit = (t: TrustAccount) => {
    setEditingTrust(t);
    setTrustName(t.name);
    setTrustBank(t.bank_name ?? '');
    setTrustLast4(t.account_number_last4 ?? '');
    setTrustOpen(true);
  };

  const saveTrust = async () => {
    if (!trustName.trim()) {
      addFlash({ type: 'error', content: 'Account name is required.' });
      return;
    }
    setSavingTrust(true);
    try {
      const payload = {
        name: trustName.trim(),
        bank_name: trustBank.trim() || null,
        account_number_last4: trustLast4.trim() || null,
      };
      if (editingTrust) {
        await ownersApi.updateTrustAccount(editingTrust.id, payload);
        addFlash({ type: 'success', content: 'Trust account updated.' });
      } else {
        await ownersApi.createTrustAccount(payload);
        addFlash({ type: 'success', content: 'Trust account created.' });
      }
      setTrustOpen(false);
      await loadTop();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save trust account.' });
    } finally {
      setSavingTrust(false);
    }
  };

  const reviewTrust = async (t: TrustAccount) => {
    const status = window.prompt(
      `Compliance status (${COMPLIANCE_STATUSES.join(', ')})`,
      t.compliance_status,
    );
    if (status == null) return;
    if (!COMPLIANCE_STATUSES.includes(status as ComplianceStatus)) {
      addFlash({ type: 'error', content: 'Invalid compliance status.' });
      return;
    }
    try {
      await ownersApi.reviewTrustAccount(t.id, { compliance_status: status });
      addFlash({ type: 'success', content: 'Compliance review recorded.' });
      await loadTop();
    } catch {
      addFlash({ type: 'error', content: 'Failed to record review.' });
    }
  };

  return (
    <SpaceBetween size="l">
      <Table<PropertyOwner>
        loading={loading}
        items={ownersList}
        variant="container"
        selectionType="single"
        selectedItems={detailOwner ? [detailOwner] : []}
        onSelectionChange={({ detail }) => {
          const o = detail.selectedItems[0];
          if (o) openDetail(o);
        }}
        header={
          <Header
            counter={`(${ownersList.length})`}
            actions={
              <Button variant="primary" onClick={openOwnerCreate}>
                Add owner
              </Button>
            }
          >
            Property owners
          </Header>
        }
        columnDefinitions={[
          { id: 'name', header: 'Name', cell: (o) => o.name },
          { id: 'email', header: 'Email', cell: (o) => o.email ?? '—' },
          {
            id: 'fee',
            header: 'Mgmt fee %',
            cell: (o) => `${Number(o.management_fee_percent).toFixed(2)}%`,
          },
          { id: 'status', header: 'Status', cell: (o) => ownerBadge(o.status) },
          {
            id: 'actions',
            header: 'Actions',
            cell: (o) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => openDetail(o)}>
                  Ledger
                </Button>
                <Button variant="inline-link" onClick={() => openOwnerEdit(o)}>
                  Edit
                </Button>
                <PortalInviteButton
                  entityLabel="owner"
                  entityName={o.name}
                  onInvite={() => ownersApi.inviteToPortal(o.id)}
                />
                <Button variant="inline-link" onClick={() => removeOwner(o)}>
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No owners yet.</Box>}
      />

      {detailOwner && (
        <Container
          header={
            <Header
              variant="h3"
              description={
                balance
                  ? `Current balance due to owner: ${fmtMoney(balance.balance)}`
                  : 'Loading balance…'
              }
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button onClick={() => setLedgerOpen(true)}>Add ledger entry</Button>
                  <Button onClick={() => setDistOpen(true)}>New distribution</Button>
                  <Button variant="link" onClick={() => setDetailOwner(null)}>
                    Close
                  </Button>
                </SpaceBetween>
              }
            >
              {detailOwner.name}
            </Header>
          }
        >
          <SpaceBetween size="l">
            <Table<OwnerLedgerEntry>
              items={ledger}
              variant="embedded"
              header={<Header variant="h3">Ledger</Header>}
              columnDefinitions={[
                { id: 'date', header: 'Date', cell: (e) => e.entry_date },
                { id: 'type', header: 'Type', cell: (e) => e.entry_type },
                { id: 'amount', header: 'Amount', cell: (e) => fmtMoney(e.amount) },
                { id: 'desc', header: 'Description', cell: (e) => e.description ?? '—' },
              ]}
              empty={<Box textAlign="center">No ledger entries.</Box>}
            />
            <Table<OwnerDistribution>
              items={distributions}
              variant="embedded"
              header={<Header variant="h3">Distributions</Header>}
              columnDefinitions={[
                { id: 'date', header: 'Date', cell: (d) => d.distribution_date },
                { id: 'amount', header: 'Amount', cell: (d) => fmtMoney(d.amount) },
                { id: 'method', header: 'Method', cell: (d) => d.method },
                {
                  id: 'status',
                  header: 'Status',
                  cell: (d) => (
                    <Badge
                      color={d.status === 'paid' ? 'green' : d.status === 'void' ? 'red' : 'blue'}
                    >
                      {d.status}
                    </Badge>
                  ),
                },
                {
                  id: 'actions',
                  header: 'Actions',
                  cell: (d) =>
                    d.status === 'pending' ? (
                      <SpaceBetween direction="horizontal" size="xs">
                        <Button variant="inline-link" onClick={() => payDist(d)}>
                          Mark paid
                        </Button>
                        <Button variant="inline-link" onClick={() => voidDist(d)}>
                          Void
                        </Button>
                      </SpaceBetween>
                    ) : (
                      '—'
                    ),
                },
              ]}
              empty={<Box textAlign="center">No distributions.</Box>}
            />
          </SpaceBetween>
        </Container>
      )}

      <Table<TrustAccount>
        loading={loading}
        items={trustAccounts}
        variant="container"
        header={
          <Header
            counter={`(${trustAccounts.length})`}
            actions={
              <Button variant="primary" onClick={openTrustCreate}>
                Add trust account
              </Button>
            }
          >
            Trust / escrow accounts
          </Header>
        }
        columnDefinitions={[
          { id: 'name', header: 'Name', cell: (t) => t.name },
          { id: 'bank', header: 'Bank', cell: (t) => t.bank_name ?? '—' },
          {
            id: 'last4',
            header: 'Account',
            cell: (t) => (t.account_number_last4 ? `••••${t.account_number_last4}` : '—'),
          },
          {
            id: 'compliance',
            header: 'Compliance',
            cell: (t) => complianceBadge(t.compliance_status),
          },
          {
            id: 'actions',
            header: 'Actions',
            cell: (t) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button variant="inline-link" onClick={() => reviewTrust(t)}>
                  Review
                </Button>
                <Button variant="inline-link" onClick={() => openTrustEdit(t)}>
                  Edit
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={<Box textAlign="center">No trust accounts yet.</Box>}
      />

      {/* Owner modal */}
      <Modal
        visible={ownerOpen}
        onDismiss={() => setOwnerOpen(false)}
        header={editing ? 'Edit owner' : 'Add owner'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setOwnerOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={savingOwner} onClick={saveOwner}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Name">
            <Input value={name} onChange={({ detail }) => setName(detail.value)} />
          </FormField>
          <ColumnLayout columns={2}>
            <FormField label="Email">
              <Input value={email} onChange={({ detail }) => setEmail(detail.value)} />
            </FormField>
            <FormField label="Phone">
              <Input value={phone} onChange={({ detail }) => setPhone(detail.value)} />
            </FormField>
            <FormField label="Management fee %">
              <Input
                type="number"
                value={feePercent}
                onChange={({ detail }) => setFeePercent(detail.value)}
              />
            </FormField>
            <FormField label="Status">
              <Select
                selectedOption={{ label: statusValue, value: statusValue }}
                onChange={({ detail }) =>
                  setStatusValue(detail.selectedOption.value as OwnerStatus)
                }
                options={OWNER_STATUSES.map((s) => ({ label: s, value: s }))}
              />
            </FormField>
          </ColumnLayout>
          <FormField label="Notes">
            <Textarea value={notes} onChange={({ detail }) => setNotes(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Ledger entry modal */}
      <Modal
        visible={ledgerOpen}
        onDismiss={() => setLedgerOpen(false)}
        header="Add ledger entry"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setLedgerOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={savingEntry} onClick={saveEntry}>
                Post
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Entry type">
            <Select
              selectedOption={{ label: entryType, value: entryType }}
              onChange={({ detail }) =>
                setEntryType(detail.selectedOption.value as LedgerEntryType)
              }
              options={LEDGER_ENTRY_TYPES.map((t) => ({ label: t, value: t }))}
            />
          </FormField>
          <FormField label="Amount">
            <Input
              type="number"
              value={entryAmount}
              onChange={({ detail }) => setEntryAmount(detail.value)}
            />
          </FormField>
          <FormField label="Description">
            <Input value={entryDesc} onChange={({ detail }) => setEntryDesc(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Distribution modal */}
      <Modal
        visible={distOpen}
        onDismiss={() => setDistOpen(false)}
        header="New distribution"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setDistOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={savingDist} onClick={saveDist}>
                Create
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Amount">
            <Input
              type="number"
              value={distAmount}
              onChange={({ detail }) => setDistAmount(detail.value)}
            />
          </FormField>
          <FormField label="Method">
            <Select
              selectedOption={{ label: distMethod, value: distMethod }}
              onChange={({ detail }) =>
                setDistMethod(detail.selectedOption.value as DistributionMethod)
              }
              options={DISTRIBUTION_METHODS.map((m) => ({ label: m, value: m }))}
            />
          </FormField>
          <FormField label="Memo">
            <Input value={distMemo} onChange={({ detail }) => setDistMemo(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>

      {/* Trust account modal */}
      <Modal
        visible={trustOpen}
        onDismiss={() => setTrustOpen(false)}
        header={editingTrust ? 'Edit trust account' : 'Add trust account'}
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setTrustOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={savingTrust} onClick={saveTrust}>
                Save
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Account name">
            <Input value={trustName} onChange={({ detail }) => setTrustName(detail.value)} />
          </FormField>
          <FormField label="Bank name">
            <Input value={trustBank} onChange={({ detail }) => setTrustBank(detail.value)} />
          </FormField>
          <FormField label="Account number (last 4)">
            <Input value={trustLast4} onChange={({ detail }) => setTrustLast4(detail.value)} />
          </FormField>
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
};

export default OwnersPage;
