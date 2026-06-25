import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Spinner from '@cloudscape-design/components/spinner';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import Badge from '@cloudscape-design/components/badge';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import { leases as leasesApi } from '@/api';
import type { Lease } from '@/types';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function daysUntil(dateStr: string): number {
  return Math.floor((new Date(dateStr).getTime() - Date.now()) / 86_400_000);
}

function urgencyBadgeColor(days: number): 'red' | 'blue' | 'grey' {
  if (days < 90) return 'red';
  if (days < 180) return 'blue';
  return 'grey';
}

const LeaseCalendarPage: React.FC = () => {
  const navigate = useNavigate();
  const [leases, setLeases] = useState<Lease[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await leasesApi.list({ page_size: 1000 });
        setLeases(res.data.items.filter((l: Lease) => l.lease_expiration));
      } catch {
        setError('Failed to load leases.');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const leasesByMonth = MONTHS.map((_, monthIdx) => {
    return leases.filter((l) => {
      if (!l.lease_expiration) return false;
      const d = new Date(l.lease_expiration);
      return d.getFullYear() === year && d.getMonth() === monthIdx;
    });
  });

  const totalYear = leasesByMonth.reduce((sum, m) => sum + m.length, 0);

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[
              { text: 'Home', href: '/' },
              { text: 'Leases', href: '/leases' },
              { text: 'Calendar', href: '/leases/calendar' },
            ]}
            onFollow={(e) => { e.preventDefault(); navigate(e.detail.href); }}
          />
          <Header
            variant="h1"
            description={`${totalYear} lease${totalYear !== 1 ? 's' : ''} expiring in ${year}`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button iconName="angle-left" onClick={() => setYear((y) => y - 1)} />
                <Box variant="h3" padding={{ top: 'xxs' }}>{year}</Box>
                <Button iconName="angle-right" onClick={() => setYear((y) => y + 1)} />
              </SpaceBetween>
            }
          >
            Lease Expiration Calendar
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        {error && <Alert type="error">{error}</Alert>}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: '16px',
          }}
        >
          {MONTHS.map((month, idx) => {
            const monthLeases = leasesByMonth[idx];
            return (
              <div
                key={month}
                style={{
                  border: '1px solid var(--color-border-divider-default, #e9ebed)',
                  borderRadius: '8px',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    background: monthLeases.length > 0 ? 'var(--color-background-notification-blue, #e6f2ff)' : 'var(--color-background-container-header, #f8f8f8)',
                    padding: '8px 12px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    borderBottom: '1px solid var(--color-border-divider-default, #e9ebed)',
                  }}
                >
                  <strong>{month}</strong>
                  {monthLeases.length > 0 && (
                    <Badge color={monthLeases.some((l) => daysUntil(l.lease_expiration!) < 90) ? 'red' : 'blue'}>
                      {monthLeases.length}
                    </Badge>
                  )}
                </div>
                <div style={{ padding: '8px 12px', minHeight: '60px' }}>
                  {monthLeases.length === 0 ? (
                    <Box color="text-body-secondary" fontSize="body-s">No expirations</Box>
                  ) : (
                    <SpaceBetween size="xxs">
                      {monthLeases.map((l) => {
                        const days = daysUntil(l.lease_expiration!);
                        return (
                          <div
                            key={l.id}
                            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                            onClick={() => navigate(`/leases/${l.id}`)}
                          >
                            <Box fontSize="body-s" color="text-interactive-default">
                              {l.lease_name}
                            </Box>
                            <Badge color={urgencyBadgeColor(days)}>
                              {new Date(l.lease_expiration!).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                            </Badge>
                          </div>
                        );
                      })}
                    </SpaceBetween>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </SpaceBetween>
    </ContentLayout>
  );
};

export default LeaseCalendarPage;
