import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Link from '@cloudscape-design/components/link';
import Table from '@cloudscape-design/components/table';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Pagination from '@cloudscape-design/components/pagination';
import FormField from '@cloudscape-design/components/form-field';
import Textarea from '@cloudscape-design/components/textarea';
import Modal from '@cloudscape-design/components/modal';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import { leases as leasesApi, reports as reportsApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import ActivityTimeline from '@/components/common/ActivityTimeline';
import ConfirmDeleteModal from '@/components/common/ConfirmDeleteModal';
import LeaseAbstractSection from '@/components/common/LeaseAbstractSection';
import LeaseDocumentSearch from '@/components/common/LeaseDocumentSearch';
import type { Lease, LeaseNote, LeaseAccountingResponse, LeaseRenewal, LeaseOption } from '@/types';
import { leaseStatusLabel } from '@/constants/leaseStatus';

const ACCOUNTING_EXPANDED_KEY = 'leaseDetail.accountingExpanded';

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value ?? '—'}</Box>
  </div>
);

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString();
}

function daysUntil(dateStr?: string): number | null {
  if (!dateStr) return null;
  return Math.floor((new Date(dateStr).getTime() - Date.now()) / 86_400_000);
}

function formatCurrency(value: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: 2 }).format(value);
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(4)}%`;
}

const LeaseDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const [lease, setLease] = useState<Lease | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Notes state
  const [newNote, setNewNote] = useState('');
  const [addingNote, setAddingNote] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);
  const [renewing, setRenewing] = useState(false);
  const [markingNotice, setMarkingNotice] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Lease accounting
  const [accountingExpanded, setAccountingExpanded] = useState<boolean>(() => {
    try {
      return localStorage.getItem(ACCOUNTING_EXPANDED_KEY) === 'true';
    } catch {
      return false;
    }
  });
  const [accounting, setAccounting] = useState<LeaseAccountingResponse | null>(null);
  const [accountingLoading, setAccountingLoading] = useState(false);
  const [accountingError, setAccountingError] = useState<string | null>(null);
  const [schedPage, setSchedPage] = useState(1);
  const [journalEntries, setJournalEntries] = useState<LeaseAccountingResponse['journal_entries'] | null>(null);
  const [journalLoading, setJournalLoading] = useState(false);

  const SCHED_PAGE_SIZE = 24;

  // Renewal workflow state
  const [renewalExpanded, setRenewalExpanded] = useState(false);
  const [renewals, setRenewals] = useState<LeaseRenewal[]>([]);
  const [renewalsLoading, setRenewalsLoading] = useState(false);
  const [startRenewalVisible, setStartRenewalVisible] = useState(false);
  const [renewalForm, setRenewalForm] = useState({ target_expiration: '', new_rent_amount: '', notes: '' });
  const [startingRenewal, setStartingRenewal] = useState(false);
  const [advancingRenewalId, setAdvancingRenewalId] = useState<string | null>(null);

  // Lease options state
  const [optionsExpanded, setOptionsExpanded] = useState(false);
  const [options, setOptions] = useState<LeaseOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [addOptionVisible, setAddOptionVisible] = useState(false);
  const [optionForm, setOptionForm] = useState({
    option_type: 'renewal',
    exercise_window_start: '',
    exercise_window_end: '',
    notice_required_days: '',
    new_term_months: '',
    new_rent_amount: '',
    notes: '',
  });
  const [savingOption, setSavingOption] = useState(false);
  const [updatingOptionId, setUpdatingOptionId] = useState<string | null>(null);

  const fetchLease = useCallback(async () => {
    if (!id) return;
    try {
      const res = await leasesApi.get(id);
      setLease(res.data);
    } catch {
      setError('Failed to load lease details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchRenewals = useCallback(async () => {
    if (!id) return;
    setRenewalsLoading(true);
    try {
      const res = await leasesApi.listRenewals(id);
      setRenewals(res.data);
    } catch {
      // best-effort
    } finally {
      setRenewalsLoading(false);
    }
  }, [id]);

  const handleStartRenewal = async () => {
    if (!id) return;
    setStartingRenewal(true);
    try {
      await leasesApi.createRenewal(id, {
        target_expiration: renewalForm.target_expiration || undefined,
        new_rent_amount: renewalForm.new_rent_amount ? parseFloat(renewalForm.new_rent_amount) : undefined,
        notes: renewalForm.notes || undefined,
      });
      setStartRenewalVisible(false);
      await fetchRenewals();
    } catch {
      addFlash({ type: 'error', content: 'Failed to start renewal.' });
    } finally {
      setStartingRenewal(false);
    }
  };

  const handleAdvanceRenewal = async (renewal: LeaseRenewal, action: string) => {
    if (!id) return;
    setAdvancingRenewalId(renewal.id);
    const now = new Date().toISOString();
    let updatePayload: Partial<LeaseRenewal> = {};
    if (action === 'notice') updatePayload = { notice_sent_at: now };
    else if (action === 'terms') updatePayload = { status: 'terms_agreed', terms_agreed_at: now };
    else if (action === 'execute') updatePayload = { status: 'executed', executed_at: now };
    else if (action === 'abandon') updatePayload = { status: 'abandoned' };
    try {
      await leasesApi.updateRenewal(id, renewal.id, updatePayload);
      await fetchRenewals();
    } catch {
      addFlash({ type: 'error', content: 'Failed to update renewal.' });
    } finally {
      setAdvancingRenewalId(null);
    }
  };

  const fetchOptions = useCallback(async () => {
    if (!id) return;
    setOptionsLoading(true);
    try {
      const res = await leasesApi.listOptions(id);
      setOptions(res.data);
    } catch {
      // best-effort
    } finally {
      setOptionsLoading(false);
    }
  }, [id]);

  const handleExportAmortization = async () => {
    if (!id) return;
    try {
      const res = await reportsApi.exportAmortizationCsv(id);
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `amortization_${id}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      addFlash({ type: 'error', content: 'Failed to export amortization schedule.' });
    }
  };

  const handleAddOption = async () => {
    if (!id) return;
    setSavingOption(true);
    try {
      await leasesApi.createOption(id, {
        option_type: optionForm.option_type,
        exercise_window_start: optionForm.exercise_window_start || undefined,
        exercise_window_end: optionForm.exercise_window_end || undefined,
        notice_required_days: optionForm.notice_required_days ? parseInt(optionForm.notice_required_days) : undefined,
        new_term_months: optionForm.new_term_months ? parseInt(optionForm.new_term_months) : undefined,
        new_rent_amount: optionForm.new_rent_amount ? parseFloat(optionForm.new_rent_amount) : undefined,
        notes: optionForm.notes || undefined,
      });
      setAddOptionVisible(false);
      await fetchOptions();
      addFlash({ type: 'success', content: 'Option added.' });
    } catch {
      addFlash({ type: 'error', content: 'Failed to add option.' });
    } finally {
      setSavingOption(false);
    }
  };

  const handleUpdateOptionStatus = async (option: LeaseOption, newStatus: string) => {
    if (!id) return;
    setUpdatingOptionId(option.id);
    try {
      await leasesApi.updateOption(id, option.id, { status: newStatus });
      await fetchOptions();
    } catch {
      addFlash({ type: 'error', content: 'Failed to update option.' });
    } finally {
      setUpdatingOptionId(null);
    }
  };

  const handleDeleteOption = async (option: LeaseOption) => {
    if (!id) return;
    setUpdatingOptionId(option.id);
    try {
      await leasesApi.deleteOption(id, option.id);
      await fetchOptions();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete option.' });
    } finally {
      setUpdatingOptionId(null);
    }
  };

  const loadAccounting = useCallback(async () => {
    if (!accounting && !accountingLoading && id) {
      setAccountingLoading(true);
      setAccountingError(null);
      try {
        const res = await leasesApi.getAccounting(id);
        setAccounting(res.data);
      } catch {
        setAccountingError('Failed to load accounting data.');
      } finally {
        setAccountingLoading(false);
      }
    }
  }, [accounting, accountingLoading, id]);

  const handleAccountingExpand = (expanded: boolean) => {
    setAccountingExpanded(expanded);
    try {
      localStorage.setItem(ACCOUNTING_EXPANDED_KEY, String(expanded));
    } catch {
      // ignore storage errors (e.g., private mode)
    }
    if (expanded) {
      loadAccounting();
    }
  };

  const handleLoadJournalEntries = async () => {
    if (!id) return;
    setJournalLoading(true);
    try {
      const res = await leasesApi.getAccounting(id, true);
      setJournalEntries(res.data.journal_entries);
    } catch {
      setAccountingError('Failed to load journal entries.');
    } finally {
      setJournalLoading(false);
    }
  };

  useEffect(() => {
    fetchLease();
  }, [fetchLease]);

  // Auto-load accounting data when the section was restored in the expanded state.
  useEffect(() => {
    if (accountingExpanded && lease?.accounting_standard && id) {
      loadAccounting();
    }
  }, [accountingExpanded, lease?.accounting_standard, id, loadAccounting]);

  const handleRenew = async () => {
    if (!id) return;
    setRenewing(true);
    try {
      const res = await leasesApi.clone(id);
      navigate(`/leases/${res.data.id}/edit`);
    } catch {
      setError('Failed to create renewal lease.');
    } finally {
      setRenewing(false);
    }
  };

  const handleMarkNoticeGiven = async () => {
    if (!id) return;
    setMarkingNotice(true);
    try {
      const today = new Date().toISOString().split('T')[0];
      await leasesApi.update(id, { notice_given_date: today });
      await fetchLease();
    } catch {
      setError('Failed to mark notice as given.');
    } finally {
      setMarkingNotice(false);
    }
  };

  const handleDelete = () => setShowDeleteModal(true);

  const confirmDelete = async () => {
    if (!id || !lease) return;
    setDeleting(true);
    try {
      await leasesApi.delete(id);
      const label = lease.lease_name;
      setShowDeleteModal(false);
      navigate('/leases');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button variant="link" onClick={async () => {
              try {
                await leasesApi.restore(id);
                navigate(`/leases/${id}`);
              } catch {
                addFlash({ type: 'error', content: 'Failed to undo delete.' });
              }
            }}>Undo</Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete lease.');
      setDeleting(false);
    }
  };

  const handleAddNote = async () => {
    if (!id || !newNote.trim()) return;
    setAddingNote(true);
    setNoteError(null);
    try {
      await leasesApi.addNote(id, newNote.trim());
      setNewNote('');
      await fetchLease();
    } catch {
      setNoteError('Failed to add note. Please try again.');
    } finally {
      setAddingNote(false);
    }
  };

  const handleDeleteNote = async (noteId: string) => {
    if (!id) return;
    setDeletingNoteId(noteId);
    try {
      await leasesApi.deleteNote(id, noteId);
      await fetchLease();
    } catch {
      setNoteError('Failed to delete note.');
    } finally {
      setDeletingNoteId(null);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (error && !lease) {
    return <Alert type="error">{error}</Alert>;
  }

  if (!lease) {
    return <Alert type="error">Lease not found.</Alert>;
  }

  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const days = daysUntil(lease.lease_expiration);
  const expirationStatus =
    days === null ? null : days < 90 ? 'error' : days < 180 ? 'warning' : 'success';

  const sortedNotes = [...(lease.notes ?? [])].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  const noteColumns = [
    {
      id: 'note',
      header: 'Note',
      cell: (item: LeaseNote) => item.note_text,
    },
    {
      id: 'created_at',
      header: 'Date',
      cell: (item: LeaseNote) => new Date(item.created_at).toLocaleString(),
    },
    {
      id: 'actions',
      header: '',
      cell: (item: LeaseNote) => (
        <Button
          variant="inline-icon"
          iconName="remove"
          ariaLabel="Delete note"
          loading={deletingNoteId === item.id}
          onClick={() => handleDeleteNote(item.id)}
        />
      ),
    },
  ];

  const renewalStatusIndicator = (r: LeaseRenewal) => {
    const map: Record<string, { type: 'info' | 'success' | 'stopped' | 'pending'; label: string }> = {
      in_progress: { type: 'info', label: 'In Progress' },
      terms_agreed: { type: 'success', label: 'Terms Agreed' },
      executed: { type: 'success', label: 'Executed' },
      abandoned: { type: 'stopped', label: 'Abandoned' },
    };
    const s = map[r.status] ?? { type: 'pending' as const, label: r.status };
    return <StatusIndicator type={s.type}>{s.label}</StatusIndicator>;
  };

  const renewalActions = (r: LeaseRenewal) => {
    if (r.status === 'executed' || r.status === 'abandoned') return null;
    return (
      <SpaceBetween direction="horizontal" size="xs">
        {r.status === 'in_progress' && !r.notice_sent_at && (
          <Button size="small" loading={advancingRenewalId === r.id} onClick={() => handleAdvanceRenewal(r, 'notice')}>Send Notice</Button>
        )}
        {r.status === 'in_progress' && r.notice_sent_at && (
          <Button size="small" loading={advancingRenewalId === r.id} onClick={() => handleAdvanceRenewal(r, 'terms')}>Terms Agreed</Button>
        )}
        {r.status === 'terms_agreed' && (
          <Button size="small" loading={advancingRenewalId === r.id} onClick={() => handleAdvanceRenewal(r, 'execute')}>Mark Executed</Button>
        )}
        {user?.role === 'admin' && (
          <Button size="small" variant="inline-link" loading={advancingRenewalId === r.id} onClick={() => handleAdvanceRenewal(r, 'abandon')}>Abandon</Button>
        )}
      </SpaceBetween>
    );
  };

  const optionStatusIndicator = (o: LeaseOption) => {
    const map: Record<string, { type: 'success' | 'error' | 'stopped' | 'pending' | 'warning'; label: string }> = {
      open: { type: 'pending', label: 'Open' },
      exercised: { type: 'success', label: 'Exercised' },
      expired: { type: 'error', label: 'Expired' },
      waived: { type: 'stopped', label: 'Waived' },
    };
    const s = map[o.status] ?? { type: 'pending' as const, label: o.status };
    return <StatusIndicator type={s.type}>{s.label}</StatusIndicator>;
  };

  const optionTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      renewal: 'Renewal', expansion: 'Expansion', termination: 'Termination',
      rofo: 'ROFO', rofr: 'ROFR', purchase: 'Purchase',
    };
    return labels[type] ?? type;
  };

  const optionDaysUrgency = (o: LeaseOption) => {
    if (!o.exercise_window_end || o.status !== 'open') return null;
    const days = Math.floor((new Date(o.exercise_window_end).getTime() - Date.now()) / 86_400_000);
    if (days < 0) return <StatusIndicator type="error">Expired {Math.abs(days)}d ago</StatusIndicator>;
    if (days <= 30) return <StatusIndicator type="warning">{days}d left</StatusIndicator>;
    if (days <= 90) return <StatusIndicator type="info">{days}d left</StatusIndicator>;
    return <>{days}d left</>;
  };

  return (
    <>
      <ConfirmDeleteModal
        visible={showDeleteModal}
        itemName={lease.lease_name}
        onConfirm={confirmDelete}
        onCancel={() => setShowDeleteModal(false)}
        loading={deleting}
      />
      <Modal
        visible={startRenewalVisible}
        onDismiss={() => setStartRenewalVisible(false)}
        header="Start Renewal"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setStartRenewalVisible(false)}>Cancel</Button>
              <Button variant="primary" loading={startingRenewal} onClick={handleStartRenewal}>Start</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Target Expiration Date">
            <Input
              type="date"
              value={renewalForm.target_expiration}
              onChange={({ detail }) => setRenewalForm({ ...renewalForm, target_expiration: detail.value })}
            />
          </FormField>
          <FormField label="New Rent Amount">
            <Input
              type="number"
              value={renewalForm.new_rent_amount}
              onChange={({ detail }) => setRenewalForm({ ...renewalForm, new_rent_amount: detail.value })}
              placeholder="Monthly rent amount"
            />
          </FormField>
          <FormField label="Notes">
            <Input
              value={renewalForm.notes}
              onChange={({ detail }) => setRenewalForm({ ...renewalForm, notes: detail.value })}
              placeholder="Optional notes"
            />
          </FormField>
        </SpaceBetween>
      </Modal>
      <Modal
        visible={addOptionVisible}
        onDismiss={() => setAddOptionVisible(false)}
        header="Add Lease Option"
        size="medium"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={() => setAddOptionVisible(false)}>Cancel</Button>
              <Button variant="primary" loading={savingOption} onClick={handleAddOption}>Add Option</Button>
            </SpaceBetween>
          </Box>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Option Type">
            <Select
              selectedOption={{ value: optionForm.option_type, label: optionTypeLabel(optionForm.option_type) }}
              onChange={({ detail }) => setOptionForm({ ...optionForm, option_type: detail.selectedOption.value ?? 'renewal' })}
              options={[
                { value: 'renewal', label: 'Renewal' },
                { value: 'expansion', label: 'Expansion' },
                { value: 'termination', label: 'Termination' },
                { value: 'rofo', label: 'ROFO (Right of First Offer)' },
                { value: 'rofr', label: 'ROFR (Right of First Refusal)' },
                { value: 'purchase', label: 'Purchase Option' },
              ]}
            />
          </FormField>
          <FormField label="Exercise Window Start">
            <Input type="date" value={optionForm.exercise_window_start}
              onChange={({ detail }) => setOptionForm({ ...optionForm, exercise_window_start: detail.value })} />
          </FormField>
          <FormField label="Exercise Window End (Deadline)">
            <Input type="date" value={optionForm.exercise_window_end}
              onChange={({ detail }) => setOptionForm({ ...optionForm, exercise_window_end: detail.value })} />
          </FormField>
          <FormField label="Notice Required (days)">
            <Input type="number" value={optionForm.notice_required_days}
              onChange={({ detail }) => setOptionForm({ ...optionForm, notice_required_days: detail.value })}
              placeholder="e.g. 180" />
          </FormField>
          <FormField label="New Term (months)">
            <Input type="number" value={optionForm.new_term_months}
              onChange={({ detail }) => setOptionForm({ ...optionForm, new_term_months: detail.value })}
              placeholder="e.g. 60" />
          </FormField>
          <FormField label="New Rent Amount">
            <Input type="number" value={optionForm.new_rent_amount}
              onChange={({ detail }) => setOptionForm({ ...optionForm, new_rent_amount: detail.value })}
              placeholder="Monthly rent if exercised" />
          </FormField>
          <FormField label="Notes">
            <Input value={optionForm.notes}
              onChange={({ detail }) => setOptionForm({ ...optionForm, notes: detail.value })}
              placeholder="Optional notes" />
          </FormField>
        </SpaceBetween>
      </Modal>
      <ContentLayout
        header={
          <SpaceBetween size="m">
            <BreadcrumbGroup
              items={[
                { text: 'Home', href: '/' },
                { text: 'Leases', href: '/leases' },
                { text: lease.lease_name, href: `/leases/${id}` },
              ]}
              onFollow={(e) => {
                e.preventDefault();
                navigate(e.detail.href);
              }}
            />
            <Header
              variant="h1"
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button loading={renewing} onClick={handleRenew}>Renew Lease</Button>
                  {canEdit && !lease.notice_given_date && (
                    <Button loading={markingNotice} onClick={handleMarkNoticeGiven}>Mark Notice Given</Button>
                  )}
                  <Button onClick={() => navigate(`/leases/${id}/edit`)}>Edit</Button>
                  <Button onClick={handleDelete}>Delete</Button>
                </SpaceBetween>
              }
            >
              {lease.lease_name}
            </Header>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="l">
          {error && (
            <Alert type="error" dismissible onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}

          {/* Lease Information */}
          <Container header={<Header variant="h2">Lease Details</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <ValuePair label="Lease Name" value={lease.lease_name} />
              <ValuePair
                label="Office"
                value={
                  lease.office ? (
                    <Link onFollow={() => navigate(`/offices/${lease.office!.id}`)}>
                      {lease.office.location_name}
                    </Link>
                  ) : undefined
                }
              />
              <ValuePair label="Lessor" value={lease.lessor_name} />
              <ValuePair
                label="Expiration Date"
                value={
                  expirationStatus ? (
                    <StatusIndicator type={expirationStatus}>
                      {formatDate(lease.lease_expiration)}
                    </StatusIndicator>
                  ) : (
                    '—'
                  )
                }
              />
              <ValuePair label="Notice Period" value={lease.notice_period} />
              <ValuePair label="Notice Period (days)" value={lease.notice_period_days} />
              <ValuePair label="Notice Date" value={formatDate(lease.lease_notice_date)} />
              <ValuePair label="Notice Given Date" value={formatDate(lease.notice_given_date)} />
              <ValuePair label="Status" value={leaseStatusLabel(lease.status)} />
              <ValuePair label="Expiration Year" value={lease.expiration_year} />
              <ValuePair label="Manager" value={lease.manager?.name} />
              <ValuePair label="Created" value={formatDate(lease.created_at)} />
              <ValuePair label="Last Updated" value={formatDate(lease.updated_at)} />
            </ColumnLayout>
          </Container>

          {/* Lease Abstract */}
          {id && <LeaseAbstractSection leaseId={id} canEdit={canEdit} />}

          {/* Lease Notes */}
          <Container
            header={
              <Header variant="h2" counter={`(${sortedNotes.length})`}>
                Lease Notes
              </Header>
            }
          >
            <SpaceBetween size="m">
              {noteError && (
                <Alert type="error" dismissible onDismiss={() => setNoteError(null)}>
                  {noteError}
                </Alert>
              )}
              <Table
                columnDefinitions={noteColumns}
                items={sortedNotes}
                empty={
                  <Box textAlign="center" color="inherit" padding="m">
                    No notes yet.
                  </Box>
                }
              />
              <FormField label="Add Note">
                <SpaceBetween size="xs">
                  <Textarea
                    value={newNote}
                    onChange={({ detail }) => setNewNote(detail.value)}
                    placeholder="Enter a note..."
                    rows={3}
                  />
                  <Button
                    variant="primary"
                    onClick={handleAddNote}
                    loading={addingNote}
                    disabled={!newNote.trim()}
                  >
                    Add Note
                  </Button>
                </SpaceBetween>
              </FormField>
            </SpaceBetween>
          </Container>

          {/* Attachments */}
          {id && (
            <AttachmentsPanel
              entityType="lease"
              entityId={id}
              canEdit={canEdit}
            />
          )}

          {/* Document search (keyword / semantic) */}
          {id && <LeaseDocumentSearch leaseId={id} canEdit={canEdit} />}

          {/* Lease Options */}
          <ExpandableSection
            headerText={`Lease Options${options.length > 0 ? ` (${options.length})` : ''}`}
            expanded={optionsExpanded}
            onChange={({ detail }) => {
              setOptionsExpanded(detail.expanded);
              if (detail.expanded && options.length === 0 && !optionsLoading) {
                fetchOptions();
              }
            }}
            variant="container"
          >
            {optionsLoading ? (
              <Box textAlign="center" padding="l"><Spinner size="normal" /></Box>
            ) : (
              <SpaceBetween size="m">
                {canEdit && (
                  <Box float="right">
                    <Button
                      variant="primary"
                      onClick={() => {
                        setOptionForm({ option_type: 'renewal', exercise_window_start: '', exercise_window_end: '', notice_required_days: '', new_term_months: '', new_rent_amount: '', notes: '' });
                        setAddOptionVisible(true);
                      }}
                    >
                      Add Option
                    </Button>
                  </Box>
                )}
                <Table
                  columnDefinitions={[
                    { id: 'type', header: 'Type', cell: (o: LeaseOption) => optionTypeLabel(o.option_type) },
                    { id: 'status', header: 'Status', cell: (o: LeaseOption) => optionStatusIndicator(o) },
                    { id: 'window_end', header: 'Exercise Deadline', cell: (o: LeaseOption) => o.exercise_window_end ? new Date(o.exercise_window_end).toLocaleDateString() : '—' },
                    { id: 'urgency', header: 'Days Remaining', cell: (o: LeaseOption) => optionDaysUrgency(o) ?? '—' },
                    { id: 'notice', header: 'Notice Req.', cell: (o: LeaseOption) => o.notice_required_days ? `${o.notice_required_days}d` : '—' },
                    { id: 'new_term', header: 'New Term', cell: (o: LeaseOption) => o.new_term_months ? `${o.new_term_months} mo` : '—' },
                    { id: 'new_rent', header: 'New Rent', cell: (o: LeaseOption) => o.new_rent_amount != null ? `$${o.new_rent_amount.toLocaleString()}` : '—' },
                    ...(canEdit ? [{
                      id: 'actions',
                      header: 'Actions',
                      cell: (o: LeaseOption) => o.status === 'open' ? (
                        <SpaceBetween direction="horizontal" size="xs">
                          <Button size="small" loading={updatingOptionId === o.id} onClick={() => handleUpdateOptionStatus(o, 'exercised')}>Exercise</Button>
                          <Button size="small" loading={updatingOptionId === o.id} onClick={() => handleUpdateOptionStatus(o, 'waived')}>Waive</Button>
                          <Button size="small" variant="inline-link" loading={updatingOptionId === o.id} onClick={() => handleDeleteOption(o)}>Delete</Button>
                        </SpaceBetween>
                      ) : null,
                    }] : []),
                  ]}
                  items={options}
                  empty={
                    <Box textAlign="center" color="inherit" padding="m">
                      No options recorded. Click "Add Option" to track a lease option.
                    </Box>
                  }
                />
              </SpaceBetween>
            )}
          </ExpandableSection>

          {/* Renewal Workflow */}
          <ExpandableSection
            headerText="Renewal Workflow"
            expanded={renewalExpanded}
            onChange={({ detail }) => {
              setRenewalExpanded(detail.expanded);
              if (detail.expanded && renewals.length === 0 && !renewalsLoading) {
                fetchRenewals();
              }
            }}
            variant="container"
          >
            {renewalsLoading ? (
              <Box textAlign="center" padding="l"><Spinner size="normal" /></Box>
            ) : (
              <SpaceBetween size="m">
                <Box float="right">
                  <Button variant="primary" onClick={() => { setRenewalForm({ target_expiration: '', new_rent_amount: '', notes: '' }); setStartRenewalVisible(true); }}>
                    Start Renewal
                  </Button>
                </Box>
                <Table
                  columnDefinitions={[
                    { id: 'status', header: 'Status', cell: (r: LeaseRenewal) => renewalStatusIndicator(r) },
                    { id: 'target', header: 'Target Expiration', cell: (r: LeaseRenewal) => r.target_expiration ? new Date(r.target_expiration).toLocaleDateString() : '—' },
                    { id: 'rent', header: 'New Rent', cell: (r: LeaseRenewal) => r.new_rent_amount != null ? `$${r.new_rent_amount.toLocaleString()}` : '—' },
                    { id: 'notice', header: 'Notice Sent', cell: (r: LeaseRenewal) => r.notice_sent_at ? new Date(r.notice_sent_at).toLocaleDateString() : '—' },
                    { id: 'created', header: 'Started', cell: (r: LeaseRenewal) => new Date(r.created_at).toLocaleDateString() },
                    { id: 'actions', header: 'Actions', cell: (r: LeaseRenewal) => renewalActions(r) },
                  ]}
                  items={renewals}
                  empty={
                    <Box textAlign="center" color="inherit" padding="m">
                      No renewals started yet. Click "Start Renewal" to begin the renewal process.
                    </Box>
                  }
                />
              </SpaceBetween>
            )}
          </ExpandableSection>

          {/* Lease Accounting */}
          {lease.accounting_standard && id && (            <ExpandableSection
              headerText="Lease Accounting (ASC 842 / IFRS 16)"
              expanded={accountingExpanded}
              onChange={({ detail }) => handleAccountingExpand(detail.expanded)}
              variant="container"
            >
              {accountingLoading && (
                <Box textAlign="center" padding="l">
                  <Spinner size="normal" />
                </Box>
              )}
              {accountingError && <Alert type="error">{accountingError}</Alert>}
              {accounting && (
                accounting.exempt ? (
                  <Alert type="info">{accounting.exempt_reason}</Alert>
                ) : (
                  <SpaceBetween size="l">
                    {/* Key Metrics */}
                    <ColumnLayout columns={4} variant="text-grid">
                      <ValuePair label="Initial ROU Asset" value={formatCurrency(accounting.initial_rou_asset, accounting.currency)} />
                      <ValuePair label="Initial Lease Liability" value={formatCurrency(accounting.initial_lease_liability, accounting.currency)} />
                      <ValuePair label="IBR (Annual)" value={formatPct(accounting.ibr_annual)} />
                      <ValuePair label="Term" value={`${accounting.term_months} months`} />
                    </ColumnLayout>

                    {/* Maturity Analysis */}
                    <Container header={<Header variant="h3">Maturity Analysis (Undiscounted)</Header>}>
                      <Table
                        columnDefinitions={[
                          { id: 'period', header: 'Period', cell: (item: { label: string; value: number }) => item.label },
                          { id: 'amount', header: 'Amount', cell: (item: { label: string; value: number }) => formatCurrency(item.value, accounting.currency) },
                        ]}
                        items={[
                          { label: 'Year 1', value: accounting.maturity_analysis.year_1 },
                          { label: 'Year 2', value: accounting.maturity_analysis.year_2 },
                          { label: 'Year 3', value: accounting.maturity_analysis.year_3 },
                          { label: 'Year 4', value: accounting.maturity_analysis.year_4 },
                          { label: 'Year 5', value: accounting.maturity_analysis.year_5 },
                          { label: 'Thereafter', value: accounting.maturity_analysis.thereafter },
                          { label: 'Total Undiscounted', value: accounting.maturity_analysis.total_undiscounted },
                          { label: 'Less: Imputed Interest', value: -accounting.maturity_analysis.imputed_interest },
                          { label: 'Present Value', value: accounting.maturity_analysis.present_value },
                        ]}
                      />
                    </Container>

                    {/* Amortization Schedule */}
                    <Container header={
                      <Header
                        variant="h3"
                        actions={
                          <Button iconName="download" variant="normal" onClick={handleExportAmortization}>
                            Export CSV
                          </Button>
                        }
                      >
                        Amortization Schedule
                      </Header>
                    }>
                      <SpaceBetween size="m">
                        <Table
                          columnDefinitions={[
                            { id: 'period', header: '#', cell: (item: LeaseAccountingResponse['schedule'][number]) => item.period },
                            { id: 'date', header: 'Date', cell: (item: LeaseAccountingResponse['schedule'][number]) => item.date },
                            { id: 'opening', header: 'Opening Liability', cell: (item: LeaseAccountingResponse['schedule'][number]) => formatCurrency(item.opening_liability, accounting.currency) },
                            { id: 'interest', header: 'Interest', cell: (item: LeaseAccountingResponse['schedule'][number]) => formatCurrency(item.interest, accounting.currency) },
                            { id: 'payment', header: 'Payment', cell: (item: LeaseAccountingResponse['schedule'][number]) => formatCurrency(item.payment, accounting.currency) },
                            { id: 'principal', header: 'Principal', cell: (item: LeaseAccountingResponse['schedule'][number]) => formatCurrency(item.principal, accounting.currency) },
                            { id: 'closing', header: 'Closing Liability', cell: (item: LeaseAccountingResponse['schedule'][number]) => formatCurrency(item.closing_liability, accounting.currency) },
                            { id: 'rou', header: 'ROU Carrying Value', cell: (item: LeaseAccountingResponse['schedule'][number]) => formatCurrency(item.rou_carrying_value, accounting.currency) },
                            { id: 'cost', header: 'Lease Cost', cell: (item: LeaseAccountingResponse['schedule'][number]) => formatCurrency(item.lease_cost, accounting.currency) },
                          ]}
                          items={accounting.schedule.slice((schedPage - 1) * SCHED_PAGE_SIZE, schedPage * SCHED_PAGE_SIZE)}
                        />
                        <Pagination
                          currentPageIndex={schedPage}
                          pagesCount={Math.ceil(accounting.schedule.length / SCHED_PAGE_SIZE)}
                          onChange={({ detail }) => setSchedPage(detail.currentPageIndex)}
                        />
                      </SpaceBetween>
                    </Container>

                    {/* Journal Entries */}
                    <Container header={<Header variant="h3">Journal Entries</Header>}>
                      {journalEntries ? (
                        <Table
                          columnDefinitions={[
                            { id: 'date', header: 'Date', cell: (item: LeaseAccountingResponse['journal_entries'][number]) => item.date },
                            { id: 'account', header: 'Account', cell: (item: LeaseAccountingResponse['journal_entries'][number]) => item.account },
                            { id: 'debit', header: 'Debit', cell: (item: LeaseAccountingResponse['journal_entries'][number]) => item.debit != null ? formatCurrency(item.debit, accounting.currency) : '' },
                            { id: 'credit', header: 'Credit', cell: (item: LeaseAccountingResponse['journal_entries'][number]) => item.credit != null ? formatCurrency(item.credit, accounting.currency) : '' },
                          ]}
                          items={journalEntries}
                        />
                      ) : (
                        <Button loading={journalLoading} onClick={handleLoadJournalEntries}>
                          Load Journal Entries
                        </Button>
                      )}
                    </Container>
                  </SpaceBetween>
                )
              )}
            </ExpandableSection>
          )}

          {/* Activity Log */}
          {id && <ActivityTimeline entityType="lease" entityId={id} />}
        </SpaceBetween>
      </ContentLayout>
    </>
  );
};

export default LeaseDetailPage;
