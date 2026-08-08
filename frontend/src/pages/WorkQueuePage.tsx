import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@cloudscape-design/components/alert';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Cards from '@cloudscape-design/components/cards';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Link from '@cloudscape-design/components/link';
import SegmentedControl from '@cloudscape-design/components/segmented-control';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { workQueue } from '@/api';
import type { WorkItem, WorkItemUrgency } from '@/types';

/**
 * "What needs me today" across every module.
 *
 * The rest of the product is organised by data model (Leases, Finance,
 * Maintenance, Transitions), which forces a user to tour four hubs to work out
 * what is actually outstanding. This page inverts that: one ranked list of the
 * obligations that belong to the signed-in user, each linking to the record
 * where the work gets done.
 */

const URGENCY_COLOR: Record<WorkItemUrgency, 'red' | 'severity-high' | 'blue' | 'grey'> = {
  overdue: 'red',
  critical: 'severity-high',
  urgent: 'blue',
  upcoming: 'grey',
  unscheduled: 'grey',
};

const URGENCY_LABEL: Record<WorkItemUrgency, string> = {
  overdue: 'Overdue',
  critical: 'Due now',
  urgent: 'Due soon',
  upcoming: 'Upcoming',
  unscheduled: 'No date',
};

const dueLabel = (item: WorkItem): string => {
  if (item.days_remaining === null) return item.due_date ?? 'No due date';
  if (item.days_remaining < 0) return `${Math.abs(item.days_remaining)} day(s) overdue`;
  if (item.days_remaining === 0) return 'Due today';
  return `Due in ${item.days_remaining} day(s)`;
};

const WorkQueuePage: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState<WorkItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState('all');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await workQueue.get(
        category === 'all' ? undefined : { category },
      );
      setItems(res.data.items);
      setCounts(res.data.counts);
    } catch {
      setError('Could not load your work queue.');
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    load();
  }, [load]);

  const categories = ['Finance', 'Procurement', 'Leases', 'Transitions', 'Maintenance'];

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description="Everything currently waiting on you, most urgent first."
          counter={counts.total !== undefined ? `(${counts.total})` : undefined}
          actions={<Button iconName="refresh" onClick={load} loading={loading} />}
        >
          My work
        </Header>
      }
    >
      <SpaceBetween size="l">
        {error && <Alert type="error">{error}</Alert>}

        {(counts.overdue > 0 || counts.critical > 0) && (
          <Alert type={counts.overdue > 0 ? 'error' : 'warning'}>
            {counts.overdue > 0 && <strong>{counts.overdue} overdue</strong>}
            {counts.overdue > 0 && counts.critical > 0 && ' and '}
            {counts.critical > 0 && <strong>{counts.critical} due now</strong>}
            {' '}
            item(s) need attention.
          </Alert>
        )}

        <SegmentedControl
          selectedId={category}
          onChange={({ detail }) => setCategory(detail.selectedId)}
          label="Filter by area"
          options={[
            { id: 'all', text: `All${counts.total ? ` (${counts.total})` : ''}` },
            ...categories.map(c => ({
              id: c,
              text: `${c}${counts[c] ? ` (${counts[c]})` : ''}`,
            })),
          ]}
        />

        <Cards
          loading={loading}
          loadingText="Loading your work"
          items={items}
          trackBy="id"
          cardDefinition={{
            header: item => (
              <Link
                href={item.link}
                onFollow={event => {
                  event.preventDefault();
                  navigate(item.link);
                }}
              >
                {item.title}
              </Link>
            ),
            sections: [
              {
                id: 'meta',
                content: item => (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Badge color={URGENCY_COLOR[item.urgency]}>
                      {URGENCY_LABEL[item.urgency]}
                    </Badge>
                    <Badge color="grey">{item.category}</Badge>
                    <Box variant="small" color="text-body-secondary">
                      {dueLabel(item)}
                    </Box>
                  </SpaceBetween>
                ),
              },
              {
                id: 'detail',
                content: item =>
                  item.detail ? (
                    <Box variant="small" color="text-body-secondary">
                      {item.detail}
                    </Box>
                  ) : null,
              },
            ],
          }}
          cardsPerRow={[{ cards: 1 }, { minWidth: 720, cards: 2 }]}
          empty={
            <Box textAlign="center" padding="l">
              <b>Nothing waiting on you</b>
              <Box variant="p" color="text-body-secondary">
                Approvals, renewal deadlines and assigned tasks will appear here.
              </Box>
            </Box>
          }
        />
      </SpaceBetween>
    </ContentLayout>
  );
};

export default WorkQueuePage;
