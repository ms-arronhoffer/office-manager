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
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Checkbox from '@cloudscape-design/components/checkbox';
import Input from '@cloudscape-design/components/input';
import { transitions as transitionsApi } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import { useFlashbar } from '@/context/FlashbarContext';
import AttachmentsPanel from '@/components/common/AttachmentsPanel';
import type { Transition } from '@/types';

// ─── Helpers ──────────────────────────────────────────────────────────────────

const capitalize = (s: string) =>
  s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');

const statusIndicatorType = (
  status: Transition['status']
): 'success' | 'in-progress' | 'pending' | 'error' => {
  switch (status) {
    case 'completed':   return 'success';
    case 'in_progress': return 'in-progress';
    case 'planned':     return 'pending';
    case 'cancelled':   return 'error';
  }
};

// ─── ValuePair ────────────────────────────────────────────────────────────────

const ValuePair: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div>
    <Box variant="awsui-key-label">{label}</Box>
    <Box>{value ?? '—'}</Box>
  </div>
);

// ─── Page ─────────────────────────────────────────────────────────────────────

const TransitionDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addFlash } = useFlashbar();

  const [transition, setTransition] = useState<Transition | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newItemText, setNewItemText] = useState('');
  const [addingItem, setAddingItem] = useState(false);

  const [togglingItems, setTogglingItems] = useState<Set<number>>(new Set());

  // ─── Fetch ──────────────────────────────────────────────────────────────────

  const fetchTransition = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const res = await transitionsApi.get(id);
      setTransition(res.data);
    } catch {
      setError('Failed to load transition details.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchTransition();
  }, [fetchTransition]);

  // ─── Checklist toggle ───────────────────────────────────────────────────────

  const handleToggleItem = async (itemId: number) => {
    if (!transition) return;
    setTogglingItems((prev) => new Set(prev).add(itemId));
    try {
      await transitionsApi.toggleChecklistItem(transition.id, itemId);
      setTransition((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          checklist_items: prev.checklist_items?.map((item) =>
            item.id === itemId ? { ...item, is_complete: !item.is_complete } : item
          ),
        };
      });
    } catch {
      setError('Failed to update checklist item.');
    } finally {
      setTogglingItems((prev) => {
        const next = new Set(prev);
        next.delete(itemId);
        return next;
      });
    }
  };

  // ─── Checklist add ──────────────────────────────────────────────────────────

  const handleAddItem = async () => {
    if (!transition || !newItemText.trim()) return;
    setAddingItem(true);
    try {
      const res = await transitionsApi.addChecklistItem(transition.id, newItemText.trim());
      setTransition((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          checklist_items: [...(prev.checklist_items ?? []), res.data],
        };
      });
      setNewItemText('');
    } catch {
      setError('Failed to add checklist item.');
    } finally {
      setAddingItem(false);
    }
  };

  // ─── Delete ─────────────────────────────────────────────────────────────────

  const handleDelete = async () => {
    if (!id || !transition) return;
    try {
      await transitionsApi.delete(id);
      const label = transition.sheet_name || `Office #${transition.office_number}`;
      navigate('/transitions');
      addFlash({
        type: 'success',
        content: (
          <span>
            Deleted <strong>{label}</strong>.{' '}
            <Button variant="link" onClick={async () => {
              try {
                await transitionsApi.restore(id);
                navigate(`/transitions/${id}`);
              } catch {
                addFlash({ type: 'error', content: 'Failed to undo delete.' });
              }
            }}>Undo</Button>
          </span>
        ),
      });
    } catch {
      setError('Failed to delete transition.');
    }
  };

  // ─── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  if (!transition) {
    return (
      <Alert type="error">{error ?? 'Transition not found.'}</Alert>
    );
  }

  // ─── Checklist stats ────────────────────────────────────────────────────────

  const checklistItems = [...(transition.checklist_items ?? [])].sort(
    (a, b) => a.sort_order - b.sort_order
  );
  const totalItems = checklistItems.length;
  const completedItems = checklistItems.filter((i) => i.is_complete).length;
  const progressValue = totalItems > 0 ? Math.round((completedItems / totalItems) * 100) : 0;

  const pageTitle = `${capitalize(transition.transition_type)}${
    transition.office ? ` — ${transition.office.location_name}` : ''
  }`;

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <>
      <ContentLayout
        header={
          <SpaceBetween size="m">
            <BreadcrumbGroup
              items={[
                { text: 'Transitions', href: '/transitions' },
                { text: pageTitle, href: `/transitions/${id}` },
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
                  <Button onClick={() => navigate(`/transitions/${id}/edit`)}>Edit</Button>
                  <Button onClick={fetchTransition} iconName="refresh" />
                  <Button
                    variant="normal"
                    onClick={handleDelete}
                  >
                    Delete
                  </Button>
                </SpaceBetween>
              }
            >
              {pageTitle}
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

          {/* ── Details container ─────────────────────────────────────────── */}
          <Container header={<Header variant="h2">Transition Details</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <ValuePair label="Office" value={transition.office?.location_name} />
              <ValuePair label="Type" value={capitalize(transition.transition_type)} />
              <ValuePair
                label="Status"
                value={
                  <StatusIndicator type={statusIndicatorType(transition.status)}>
                    {capitalize(transition.status)}
                  </StatusIndicator>
                }
              />
              <ValuePair label="Start Date" value={transition.start_date} />
              <ValuePair label="Target Date" value={transition.target_date} />
              <ValuePair label="Completed Date" value={transition.completed_date} />
            </ColumnLayout>

            {transition.notes && (
              <Box margin={{ top: 'm' }}>
                <Box variant="awsui-key-label">Notes</Box>
                <Box>{transition.notes}</Box>
              </Box>
            )}
          </Container>

          {/* ── Checklist container ───────────────────────────────────────── */}
          <Container header={<Header variant="h2">Checklist</Header>}>
            <SpaceBetween size="m">

              <ProgressBar
                value={progressValue}
                label="Completion"
                description={
                  totalItems > 0
                    ? `${completedItems} of ${totalItems} items complete`
                    : 'No checklist items yet'
                }
              />

              {checklistItems.length > 0 && (
                <SpaceBetween size="xs">
                  {checklistItems.map((item) => (
                    <Checkbox
                      key={item.id}
                      checked={item.is_complete}
                      disabled={togglingItems.has(item.id)}
                      onChange={() => handleToggleItem(item.id)}
                    >
                      {item.item_label}
                    </Checkbox>
                  ))}
                </SpaceBetween>
              )}

              {/* Add new item */}
              <SpaceBetween direction="horizontal" size="xs">
                <Input
                  value={newItemText}
                  onChange={({ detail }) => setNewItemText(detail.value)}
                  onKeyDown={({ detail }) => {
                    if (detail.key === 'Enter') handleAddItem();
                  }}
                  placeholder="New checklist item..."
                  disabled={addingItem}
                />
                <Button
                  onClick={handleAddItem}
                  loading={addingItem}
                  disabled={!newItemText.trim()}
                  iconName="add-plus"
                >
                  Add Item
                </Button>
              </SpaceBetween>

            </SpaceBetween>
          </Container>

          {/* Attachments */}
          {id && (
            <AttachmentsPanel
              entityType="transition"
              entityId={id}
              canEdit={user?.role === 'admin' || user?.role === 'editor'}
            />
          )}

        </SpaceBetween>
      </ContentLayout>
    </>
  );
};

export default TransitionDetailPage;
