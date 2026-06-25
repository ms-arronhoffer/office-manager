import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Table from '@cloudscape-design/components/table';
import FormField from '@cloudscape-design/components/form-field';
import Modal from '@cloudscape-design/components/modal';
import Input from '@cloudscape-design/components/input';
import Select from '@cloudscape-design/components/select';
import { maintenanceTickets as ticketsApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import { useWS } from '@/context/WSContext';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import ActivityTimeline from '@/components/common/ActivityTimeline';
import ConfirmDeleteModal from '@/components/common/ConfirmDeleteModal';
import MentionTextarea from '@/components/common/MentionTextarea';
import type { MaintenanceTicket, TicketNote, WorkOrderCostLine, WorkOrderCostSummary } from '@/types';

const capitalize = (s: string) =>
  s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');

const statusIndicatorType = (
  status: string
): 'success' | 'in-progress' | 'pending' => {
  switch (status) {
    case 'closed':
      return 'success';
    case 'in_progress':
      return 'in-progress';
    default:
      return 'pending';
  }
};

const priorityBadgeColor = (priority: string): 'blue' | 'grey' | 'red' => {
  switch (priority) {
    case 'high':
      return 'red';
    case 'medium':
      return 'blue';
    default:
      return 'grey';
  }
};

const fmtCurrency = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value ?? '—'}</Box>
  </div>
);

const LINE_TYPE_OPTIONS = [
  { label: 'Labor', value: 'labor' },
  { label: 'Material', value: 'material' },
];

interface CostLineForm {
  line_type: 'labor' | 'material';
  description: string;
  quantity: string;
  unit_cost: string;
}

const emptyCostForm = (): CostLineForm => ({
  line_type: 'labor',
  description: '',
  quantity: '1',
  unit_cost: '0',
});

const MaintenanceTicketDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();
  const { sendPresence, clearPresence, addMessageHandler } = useWS();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const isAdmin = user?.role === 'admin';

  // Presence
  const [viewers, setViewers] = useState<string[]>([]);
  useEffect(() => {
    if (!id) return;
    sendPresence('ticket', id);
    return () => clearPresence();
  }, [id, sendPresence, clearPresence]);

  useEffect(() => {
    return addMessageHandler((msg) => {
      if (msg.type === 'presence_update' && msg.entity_type === 'ticket' && msg.entity_id === id) {
        setViewers(msg.viewers.filter((uid) => uid !== user?.id));
      }
    });
  }, [addMessageHandler, id, user?.id]);

  const [ticket, setTicket] = useState<MaintenanceTicket | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Notes state
  const [newNote, setNewNote] = useState('');
  const [addingNote, setAddingNote] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Cost lines state
  const [costSummary, setCostSummary] = useState<WorkOrderCostSummary | null>(null);
  const [loadingCosts, setLoadingCosts] = useState(false);
  const [showCostModal, setShowCostModal] = useState(false);
  const [editingCostLine, setEditingCostLine] = useState<WorkOrderCostLine | null>(null);
  const [costForm, setCostForm] = useState<CostLineForm>(emptyCostForm());
  const [savingCost, setSavingCost] = useState(false);
  const [deletingCostId, setDeletingCostId] = useState<string | null>(null);

  const fetchTicket = useCallback(async (showSpinner = true) => {
    if (!id) return;
    if (showSpinner) setLoading(true);
    setError(null);
    try {
      const res = await ticketsApi.get(id);
      setTicket(res.data);
    } catch {
      setError('Failed to load ticket details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchCostLines = useCallback(async () => {
    if (!id) return;
    setLoadingCosts(true);
    try {
      const res = await ticketsApi.getCostLines(id);
      setCostSummary(res.data);
    } catch {
      /* silently ignore */
    } finally {
      setLoadingCosts(false);
    }
  }, [id]);

  useEffect(() => {
    fetchTicket();
  }, [fetchTicket]);

  useEffect(() => {
    fetchCostLines();
  }, [fetchCostLines]);

  const openAddCostModal = () => {
    setEditingCostLine(null);
    setCostForm(emptyCostForm());
    setShowCostModal(true);
  };

  const openEditCostModal = (line: WorkOrderCostLine) => {
    setEditingCostLine(line);
    setCostForm({
      line_type: line.line_type as 'labor' | 'material',
      description: line.description,
      quantity: String(line.quantity),
      unit_cost: String(line.unit_cost),
    });
    setShowCostModal(true);
  };

  const handleSaveCostLine = async () => {
    if (!id) return;
    setSavingCost(true);
    const payload = {
      line_type: costForm.line_type,
      description: costForm.description,
      quantity: parseFloat(costForm.quantity) || 1,
      unit_cost: parseFloat(costForm.unit_cost) || 0,
    };
    try {
      if (editingCostLine) {
        await ticketsApi.updateCostLine(id, editingCostLine.id, payload);
      } else {
        await ticketsApi.createCostLine(id, payload);
      }
      setShowCostModal(false);
      await fetchCostLines();
    } catch {
      addFlash({ type: 'error', content: 'Failed to save cost line.' });
    } finally {
      setSavingCost(false);
    }
  };

  const handleDeleteCostLine = async (lineId: string) => {
    if (!id) return;
    setDeletingCostId(lineId);
    try {
      await ticketsApi.deleteCostLine(id, lineId);
      await fetchCostLines();
    } catch {
      addFlash({ type: 'error', content: 'Failed to delete cost line.' });
    } finally {
      setDeletingCostId(null);
    }
  };

  const handleDelete = () => setShowDeleteModal(true);

  const confirmDelete = async () => {
    if (!id || !ticket) return;
    setDeleting(true);
    try {
      await ticketsApi.delete(id);
      const label = ticket.subject;
      setShowDeleteModal(false);
      navigate('/maintenance-tickets');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button variant="link" onClick={async () => {
              try {
                await ticketsApi.restore(id);
                navigate(`/maintenance-tickets/${id}`);
              } catch {
                addFlash({ type: 'error', content: 'Failed to undo delete.' });
              }
            }}>Undo</Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete ticket.');
      setDeleting(false);
    }
  };

  const handleAddNote = async () => {
    if (!id || !newNote.trim()) return;
    setAddingNote(true);
    setNoteError(null);
    try {
      await ticketsApi.addNote(id, newNote.trim());
      setNewNote('');
      await fetchTicket(false);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setNoteError(detail || 'Failed to add note. Please try again.');
    } finally {
      setAddingNote(false);
    }
  };

  const handleDeleteNote = async (noteId: string) => {
    if (!id) return;
    setDeletingNoteId(noteId);
    try {
      await ticketsApi.deleteNote(id, noteId);
      await fetchTicket(false);
    } catch {
      setNoteError('Failed to delete note.');
    } finally {
      setDeletingNoteId(null);
    }
  };

  const handleStatusChange = async (newStatus: string) => {
    if (!id) return;
    setStatusUpdating(true);
    try {
      await ticketsApi.update(id, { status: newStatus });
      await fetchTicket(false);
    } catch {
      setError('Failed to update status.');
    } finally {
      setStatusUpdating(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (!ticket) {
    return <Alert type="error">{error ?? 'Ticket not found.'}</Alert>;
  }

  const hasScheduling =
    ticket.scheduled_date ||
    ticket.estimated_duration_minutes != null ||
    ticket.actual_start_at ||
    ticket.actual_end_at ||
    ticket.technician_name;

  return (
    <>
      <ConfirmDeleteModal
        visible={showDeleteModal}
        itemName={ticket.subject}
        onConfirm={confirmDelete}
        onCancel={() => setShowDeleteModal(false)}
        loading={deleting}
      />

      {/* Cost line add/edit modal */}
      <Modal
        visible={showCostModal}
        onDismiss={() => setShowCostModal(false)}
        header={editingCostLine ? 'Edit Cost Line' : 'Add Cost Line'}
        footer={
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => setShowCostModal(false)}>Cancel</Button>
            <Button
              variant="primary"
              loading={savingCost}
              disabled={!costForm.description.trim()}
              onClick={handleSaveCostLine}
            >
              Save
            </Button>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="m">
          <FormField label="Type">
            <Select
              selectedOption={LINE_TYPE_OPTIONS.find(o => o.value === costForm.line_type) ?? LINE_TYPE_OPTIONS[0]}
              options={LINE_TYPE_OPTIONS}
              onChange={({ detail }) =>
                setCostForm(f => ({ ...f, line_type: detail.selectedOption.value as 'labor' | 'material' }))
              }
            />
          </FormField>
          <FormField label="Description">
            <Input
              value={costForm.description}
              onChange={({ detail }) => setCostForm(f => ({ ...f, description: detail.value }))}
              placeholder="e.g. Technician labor – 2 hrs"
            />
          </FormField>
          <FormField label="Quantity">
            <Input
              type="number"
              value={costForm.quantity}
              onChange={({ detail }) => setCostForm(f => ({ ...f, quantity: detail.value }))}
            />
          </FormField>
          <FormField label="Unit Cost ($)">
            <Input
              type="number"
              value={costForm.unit_cost}
              onChange={({ detail }) => setCostForm(f => ({ ...f, unit_cost: detail.value }))}
            />
          </FormField>
        </SpaceBetween>
      </Modal>

      <ContentLayout
        header={
          <SpaceBetween size="m">
            <BreadcrumbGroup
              items={[
                { text: 'Maintenance Tickets', href: '/maintenance-tickets' },
                { text: ticket.subject, href: `/maintenance-tickets/${id}` },
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
                  <Button onClick={() => { fetchTicket(); fetchCostLines(); }} iconName="refresh" />
                  {canEdit && ticket.status === 'open' && (
                    <>
                      <Button loading={statusUpdating} onClick={() => handleStatusChange('in_progress')}>
                        Mark In Progress
                      </Button>
                      <Button loading={statusUpdating} onClick={() => handleStatusChange('closed')}>
                        Close Ticket
                      </Button>
                    </>
                  )}
                  {canEdit && ticket.status === 'in_progress' && (
                    <>
                      <Button variant="primary" loading={statusUpdating} onClick={() => handleStatusChange('closed')}>
                        Close Ticket
                      </Button>
                      <Button loading={statusUpdating} onClick={() => handleStatusChange('open')}>
                        Reopen
                      </Button>
                    </>
                  )}
                  {canEdit && ticket.status === 'pending_review' && (
                    <>
                      <Button variant="primary" loading={statusUpdating} onClick={() => handleStatusChange('closed')}>
                        Approve & Close
                      </Button>
                      <Button loading={statusUpdating} onClick={() => handleStatusChange('in_progress')}>
                        Reopen
                      </Button>
                    </>
                  )}
                  {canEdit && ticket.status === 'closed' && (
                    <Button loading={statusUpdating} onClick={() => handleStatusChange('open')}>
                      Reopen Ticket
                    </Button>
                  )}
                  {canEdit && (
                    <Button onClick={() => navigate(`/maintenance-tickets/${id}/edit`)}>
                      Edit
                    </Button>
                  )}
                  {isAdmin && (
                    <Button onClick={handleDelete}>Delete</Button>
                  )}
                </SpaceBetween>
              }
            >
              {ticket.subject}
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

          {viewers.length > 0 && (
            <Alert type="info" dismissible={false}>
              {viewers.length === 1
                ? '1 other person is also viewing this ticket.'
                : `${viewers.length} other people are also viewing this ticket.`}
            </Alert>
          )}

          {/* Ticket Details */}
          <Container header={<Header variant="h2">Ticket Details</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <ValuePair
                label="Status"
                value={
                  <StatusIndicator type={statusIndicatorType(ticket.status)}>
                    {capitalize(ticket.status)}
                  </StatusIndicator>
                }
              />
              <ValuePair
                label="Priority"
                value={
                  <Badge color={priorityBadgeColor(ticket.priority)}>
                    {capitalize(ticket.priority)}
                  </Badge>
                }
              />
              <ValuePair label="Category" value={ticket.category?.name} />
              <ValuePair label="Office" value={ticket.office?.location_name} />
              <ValuePair label="Location Hours/Schedule" value={ticket.location_hours} />
              <ValuePair label="Assigned To" value={ticket.assigned_to?.name} />
              <ValuePair label="Created By" value={ticket.created_by?.display_name} />
              <ValuePair
                label="Created"
                value={ticket.created_at ? new Date(ticket.created_at).toLocaleString() : undefined}
              />
              <ValuePair
                label="Last Updated"
                value={ticket.updated_at ? new Date(ticket.updated_at).toLocaleString() : undefined}
              />
              {ticket.closed_at && (
                <ValuePair
                  label="Resolved"
                  value={new Date(ticket.closed_at).toLocaleString()}
                />
              )}
              {ticket.closed_at && ticket.created_at && (
                <ValuePair
                  label="Time to Resolution"
                  value={(() => {
                    const ms = new Date(ticket.closed_at!).getTime() - new Date(ticket.created_at).getTime();
                    const totalHours = Math.floor(ms / 3_600_000);
                    const days = Math.floor(totalHours / 24);
                    const hours = totalHours % 24;
                    return days > 0 ? `${days}d ${hours}h` : `${hours}h`;
                  })()}
                />
              )}
            </ColumnLayout>
          </Container>

          {/* Description */}
          <Container header={<Header variant="h2">Description</Header>}>
            <Box variant="p" style={{ whiteSpace: 'pre-wrap' }}>
              {ticket.description || '—'}
            </Box>
          </Container>

          {/* Scheduling & Work Order */}
          {(hasScheduling || canEdit) && (
            <Container header={<Header variant="h2">Scheduling & Work Order</Header>}>
              <ColumnLayout columns={3} variant="text-grid">
                <ValuePair
                  label="Scheduled Date"
                  value={ticket.scheduled_date ? new Date(ticket.scheduled_date).toLocaleString() : undefined}
                />
                <ValuePair
                  label="Estimated Duration"
                  value={
                    ticket.estimated_duration_minutes != null
                      ? `${ticket.estimated_duration_minutes} min`
                      : undefined
                  }
                />
                <ValuePair label="Technician" value={ticket.technician_name} />
                <ValuePair
                  label="Actual Start"
                  value={ticket.actual_start_at ? new Date(ticket.actual_start_at).toLocaleString() : undefined}
                />
                <ValuePair
                  label="Actual End"
                  value={ticket.actual_end_at ? new Date(ticket.actual_end_at).toLocaleString() : undefined}
                />
                {ticket.actual_start_at && ticket.actual_end_at && (
                  <ValuePair
                    label="Actual Duration"
                    value={(() => {
                      const ms =
                        new Date(ticket.actual_end_at!).getTime() -
                        new Date(ticket.actual_start_at!).getTime();
                      const mins = Math.round(ms / 60_000);
                      return mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins}m`;
                    })()}
                  />
                )}
              </ColumnLayout>
              {ticket.vendor_completed_at && (
                <Box margin={{ top: 'm' }}>
                  <SpaceBetween size="s">
                    <Box>
                      <Box variant="awsui-key-label">Vendor Completed At</Box>
                      <Box>{new Date(ticket.vendor_completed_at).toLocaleString()}</Box>
                    </Box>
                    {ticket.vendor_completion_notes && (
                      <Box>
                        <Box variant="awsui-key-label">Vendor Completion Notes</Box>
                        <Box style={{ whiteSpace: 'pre-wrap' }}>{ticket.vendor_completion_notes}</Box>
                      </Box>
                    )}
                  </SpaceBetween>
                </Box>
              )}
            </Container>
          )}

          {/* Work Order Costs */}
          <Container
            header={
              <Header
                variant="h2"
                counter={costSummary ? `(${costSummary.lines.length})` : undefined}
                actions={
                  canEdit && (
                    <Button onClick={openAddCostModal} iconName="add-plus">
                      Add Line
                    </Button>
                  )
                }
              >
                Work Order Costs
              </Header>
            }
          >
            {loadingCosts ? (
              <Box textAlign="center"><Spinner /></Box>
            ) : (
              <Table
                columnDefinitions={[
                  {
                    id: 'line_type',
                    header: 'Type',
                    cell: (item: WorkOrderCostLine) => capitalize(item.line_type),
                  },
                  {
                    id: 'description',
                    header: 'Description',
                    cell: (item: WorkOrderCostLine) => item.description,
                  },
                  {
                    id: 'quantity',
                    header: 'Qty',
                    cell: (item: WorkOrderCostLine) => item.quantity,
                  },
                  {
                    id: 'unit_cost',
                    header: 'Unit Cost',
                    cell: (item: WorkOrderCostLine) => fmtCurrency(Number(item.unit_cost)),
                  },
                  {
                    id: 'total_cost',
                    header: 'Total',
                    cell: (item: WorkOrderCostLine) => fmtCurrency(Number(item.total_cost)),
                  },
                  ...(canEdit
                    ? [
                        {
                          id: 'actions',
                          header: '',
                          cell: (item: WorkOrderCostLine) => (
                            <SpaceBetween direction="horizontal" size="xs">
                              <Button
                                variant="inline-icon"
                                iconName="edit"
                                ariaLabel="Edit"
                                onClick={() => openEditCostModal(item)}
                              />
                              <Button
                                variant="inline-icon"
                                iconName="remove"
                                ariaLabel="Delete"
                                loading={deletingCostId === item.id}
                                onClick={() => handleDeleteCostLine(item.id)}
                              />
                            </SpaceBetween>
                          ),
                        },
                      ]
                    : []),
                ]}
                items={costSummary?.lines ?? []}
                empty={
                  <Box textAlign="center" color="inherit" padding="m">
                    No cost lines.{canEdit && ' Add labor or materials with the button above.'}
                  </Box>
                }
                footer={
                  costSummary && costSummary.lines.length > 0 ? (
                    <ColumnLayout columns={3} variant="text-grid">
                      <ValuePair label="Labor Total" value={fmtCurrency(Number(costSummary.labor_total))} />
                      <ValuePair label="Materials Total" value={fmtCurrency(Number(costSummary.materials_total))} />
                      <ValuePair label="Grand Total" value={<strong>{fmtCurrency(Number(costSummary.grand_total))}</strong>} />
                    </ColumnLayout>
                  ) : undefined
                }
              />
            )}
          </Container>

          {/* Notes */}
          <Container
            header={
              <Header variant="h2" counter={`(${(ticket.notes ?? []).length})`}>
                Notes
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
                columnDefinitions={[
                  {
                    id: 'note',
                    header: 'Note',
                    cell: (item: TicketNote) => (
                      <span>
                        {item.note_text.split(/(@\w+)/g).map((part, i) =>
                          part.startsWith('@') ? (
                            <span key={i} style={{ color: '#7c3aed', fontWeight: 600 }}>{part}</span>
                          ) : (
                            <span key={i}>{part}</span>
                          )
                        )}
                      </span>
                    ),
                  },
                  {
                    id: 'author',
                    header: 'Author',
                    cell: (item: TicketNote) => item.created_by?.display_name ?? '—',
                  },
                  {
                    id: 'created_at',
                    header: 'Date',
                    cell: (item: TicketNote) => new Date(item.created_at).toLocaleString(),
                  },
                  ...(canEdit
                    ? [
                        {
                          id: 'actions',
                          header: '',
                          cell: (item: TicketNote) => (
                            <Button
                              variant="inline-icon"
                              iconName="remove"
                              ariaLabel="Delete note"
                              loading={deletingNoteId === item.id}
                              onClick={() => handleDeleteNote(item.id)}
                            />
                          ),
                        },
                      ]
                    : []),
                ]}
                items={[...(ticket.notes ?? [])].sort(
                  (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                )}
                empty={
                  <Box textAlign="center" color="inherit" padding="m">
                    No notes yet.
                  </Box>
                }
              />
              {canEdit && (
                <FormField label="Add Note">
                  <SpaceBetween size="xs">
                    <MentionTextarea
                      value={newNote}
                      onChange={(v) => setNewNote(v)}
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
              )}
            </SpaceBetween>
          </Container>

          {/* Attachments */}
          {id && (
            <AttachmentsPanel
              entityType="maintenance_ticket"
              entityId={id}
              canEdit={canEdit}
            />
          )}

          {/* Activity Log */}
          {id && <ActivityTimeline entityType="maintenance_ticket" entityId={id} />}
        </SpaceBetween>
      </ContentLayout>
    </>
  );
};

export default MaintenanceTicketDetailPage;
