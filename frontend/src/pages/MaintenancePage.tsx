import React, { useEffect, useMemo, useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Spinner from '@cloudscape-design/components/spinner';
import Link from '@cloudscape-design/components/link';
import TabbedPage from '@/components/layout/TabbedPage';
import MaintenanceCategoryPanel from '@/components/maintenance/MaintenanceCategoryPanel';
import { useAuth } from '@/auth/AuthContext';
import {
  maintenance as maintApi,
  offices as officesApi,
  vendors as vendorsApi,
} from '@/api';
import type {
  MaintenanceCatalog,
  MaintenanceCompliance,
  MaintenanceOverview,
  Office,
  Vendor,
} from '@/types';

interface Option { label: string; value: string; }

const rateColor = (rate: number): 'text-status-success' | 'text-status-warning' | 'text-status-error' => {
  if (rate >= 95) return 'text-status-success';
  if (rate >= 80) return 'text-status-warning';
  return 'text-status-error';
};

const OverviewTab: React.FC<{
  overview: MaintenanceOverview | null;
  compliance: MaintenanceCompliance | null;
}> = ({ overview, compliance }) => {
  if (!overview) {
    return <Box padding="m"><Spinner /> Loading overview…</Box>;
  }
  return (
    <SpaceBetween size="l">
      <ColumnLayout columns={4} variant="text-grid">
        <div><Box variant="awsui-key-label">Total tasks</Box><Box fontSize="display-l">{overview.total_tasks}</Box></div>
        <div><Box variant="awsui-key-label">Overdue</Box><Box fontSize="display-l" color="text-status-error">{overview.overdue}</Box></div>
        <div><Box variant="awsui-key-label">Due soon</Box><Box fontSize="display-l" color="text-status-info">{overview.due_soon}</Box></div>
        <div><Box variant="awsui-key-label">Expiring certs</Box><Box fontSize="display-l" color="text-status-warning">{overview.expiring_certifications}</Box></div>
      </ColumnLayout>
      {compliance && (
        <Container
          header={
            <Header
              variant="h2"
              description="On-time means the due date has not passed. Regulatory covers code-mandated work (fire/life-safety, ADA, elevator certifications)."
            >
              PM compliance
            </Header>
          }
        >
          <ColumnLayout columns={4} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">On-time rate</Box>
              <Box fontSize="display-l" color={rateColor(compliance.on_time_rate)}>{compliance.on_time_rate}%</Box>
              <Box color="text-status-inactive">{compliance.on_time} of {compliance.active_tasks} active</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Regulatory on-time</Box>
              <Box fontSize="display-l" color={rateColor(compliance.regulatory_on_time_rate)}>{compliance.regulatory_on_time_rate}%</Box>
              <Box color={compliance.regulatory_overdue ? 'text-status-error' : 'text-status-inactive'}>
                {compliance.regulatory_overdue} overdue
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Overdue tasks</Box>
              <Box fontSize="display-l" color={compliance.overdue ? 'text-status-error' : 'text-status-success'}>{compliance.overdue}</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Automation</Box>
              <Box fontSize="display-l">{compliance.automation_enabled}</Box>
              <Box color="text-status-inactive">{compliance.work_orders_generated} work orders generated</Box>
            </div>
          </ColumnLayout>
        </Container>
      )}
      <Container header={<Header variant="h2">By category</Header>}>
        <ColumnLayout columns={3} borders="horizontal">
          {overview.by_category.map((c) => (
            <div key={c.category}>
              <Box variant="awsui-key-label">{c.label}</Box>
              <Box>{c.task_count} tasks · {c.asset_count} assets</Box>
              <Box color={c.overdue ? 'text-status-error' : 'text-status-inactive'}>
                {c.overdue} overdue · {c.due_soon} due soon
              </Box>
            </div>
          ))}
        </ColumnLayout>
      </Container>
    </SpaceBetween>
  );
};

const MaintenancePage: React.FC = () => {
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';

  const [catalog, setCatalog] = useState<MaintenanceCatalog | null>(null);
  const [overview, setOverview] = useState<MaintenanceOverview | null>(null);
  const [compliance, setCompliance] = useState<MaintenanceCompliance | null>(null);
  const [vendorOptions, setVendorOptions] = useState<Option[]>([]);
  const [officeOptions, setOfficeOptions] = useState<Option[]>([]);
  const [loading, setLoading] = useState(true);

  const loadOverview = React.useCallback(() => {
    maintApi.overview().then((r) => setOverview(r.data)).catch(() => undefined);
    maintApi.compliance().then((r) => setCompliance(r.data)).catch(() => undefined);
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [catRes] = await Promise.all([maintApi.catalog()]);
        if (!active) return;
        setCatalog(catRes.data);
      } finally {
        if (active) setLoading(false);
      }
      loadOverview();
      try {
        const venRes = await vendorsApi.list({ page_size: 1000 });
        if (active) {
          setVendorOptions(
            (venRes.data.items ?? []).map((v: Vendor) => ({ label: v.company_name, value: String(v.id) })),
          );
        }
      } catch { /* optional */ }
      try {
        const offRes = await officesApi.list({ page_size: 1000 });
        if (active) {
          setOfficeOptions(
            (offRes.data.items ?? []).map((o: Office) => ({
              label: `${o.office_number} - ${o.location_name}`,
              value: String(o.id),
            })),
          );
        }
      } catch { /* optional */ }
    })();
    return () => { active = false; };
  }, [loadOverview]);

  const tabs = useMemo(() => {
    if (!catalog) return [];
    const built = [
      {
        id: 'overview',
        label: 'Overview',
        href: '/maintenance',
        content: <Box padding={{ top: 'm' }}><OverviewTab overview={overview} compliance={compliance} /></Box>,
      },
    ];
    for (const cat of catalog.categories) {
      built.push({
        id: cat.value,
        label: cat.label,
        href: `/maintenance/${cat.value}`,
        content: (
          <Box padding={{ top: 'm' }}>
            <MaintenanceCategoryPanel
              category={cat}
              frequencies={catalog.frequencies}
              taskStatuses={catalog.task_statuses}
              assetStatuses={catalog.asset_statuses}
              vendorOptions={vendorOptions}
              officeOptions={officeOptions}
              canEdit={canEdit}
              onChanged={loadOverview}
            />
          </Box>
        ),
      });
    }
    return built;
  }, [catalog, overview, compliance, vendorOptions, officeOptions, canEdit, loadOverview]);

  return (
    <ContentLayout
      header={
        <Header variant="h1" description="Track recurring upkeep, assign vendors, and schedule reminders across your portfolio.">
          Maintenance
        </Header>
      }
    >
      {loading || !catalog ? (
        <Box padding="l" textAlign="center"><Spinner size="large" /></Box>
      ) : (
        <TabbedPage ariaLabel="Maintenance" tabs={tabs} />
      )}
    </ContentLayout>
  );
};

export default MaintenancePage;
