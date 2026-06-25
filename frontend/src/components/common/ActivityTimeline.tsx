import React, { useEffect, useState, useCallback } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Table from '@cloudscape-design/components/table';
import Box from '@cloudscape-design/components/box';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { activityLog } from '@/api';
import type { ActivityLogEntry } from '@/types';

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

function actionIndicator(action: string) {
  switch (action) {
    case 'created':
      return <StatusIndicator type="success">Created</StatusIndicator>;
    case 'updated':
      return <StatusIndicator type="info">Updated</StatusIndicator>;
    case 'deleted':
      return <StatusIndicator type="error">Deleted</StatusIndicator>;
    case 'status_changed':
      return <StatusIndicator type="in-progress">Status changed</StatusIndicator>;
    default:
      return <StatusIndicator type="info">{action}</StatusIndicator>;
  }
}

function formatChanges(changes: Record<string, { old: unknown; new: unknown }> | null): string {
  if (!changes || Object.keys(changes).length === 0) return '';
  return Object.entries(changes)
    .map(([field, { old: oldVal, new: newVal }]) => {
      const label = field.replace(/_/g, ' ');
      return `${label}: ${oldVal ?? '(empty)'} → ${newVal ?? '(empty)'}`;
    })
    .join('; ');
}

interface ActivityTimelineProps {
  entityType: string;
  entityId: string;
}

const ActivityTimeline: React.FC<ActivityTimelineProps> = ({ entityType, entityId }) => {
  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchActivity = useCallback(async () => {
    setLoading(true);
    try {
      const res = await activityLog.list({ entity_type: entityType, entity_id: entityId, limit: 50 });
      setEntries(res.data);
    } catch {
      // non-critical
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId]);

  useEffect(() => {
    fetchActivity();
  }, [fetchActivity]);

  return (
    <Container
      header={
        <Header variant="h2" counter={loading ? undefined : `(${entries.length})`}>
          Activity Log
        </Header>
      }
    >
      <Table
        loading={loading}
        loadingText="Loading activity..."
        columnDefinitions={[
          {
            id: 'user',
            header: 'User',
            cell: (item: ActivityLogEntry) => item.user_display_name || '—',
          },
          {
            id: 'action',
            header: 'Action',
            cell: (item: ActivityLogEntry) => actionIndicator(item.action),
          },
          {
            id: 'changes',
            header: 'Changes',
            cell: (item: ActivityLogEntry) => {
              const text = formatChanges(item.changes as Record<string, { old: unknown; new: unknown }> | null);
              return text || '—';
            },
          },
          {
            id: 'time',
            header: 'Time',
            cell: (item: ActivityLogEntry) => relativeTime(item.created_at),
          },
        ]}
        items={entries}
        empty={
          <Box textAlign="center" color="inherit" padding="m">
            No activity recorded yet.
          </Box>
        }
        variant="embedded"
      />
    </Container>
  );
};

export default ActivityTimeline;
