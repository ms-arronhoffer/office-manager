import React from 'react';
import TabbedPage from '@/components/layout/TabbedPage';
import DashboardPage from '@/pages/DashboardPage';
import FinancialDashboardPage from '@/pages/FinancialDashboardPage';
import AnalyticsPage from '@/pages/AnalyticsPage';
import ReportsPage from '@/pages/ReportsPage';
import SlaDashboardPage from '@/pages/SlaDashboardPage';

/**
 * Dashboard hub — merges the four previously separate dashboard surfaces
 * (home overview, Financial, Analytics, SLA) plus Reports into a single
 * tabbed destination. Reports is grouped next to Analytics as the combined
 * analytics/reporting surface.
 *
 * All tabs are ungated (they were ungated routes previously), so no role
 * filtering is required here.
 */
const DashboardHubPage: React.FC = () => (
  <TabbedPage
    ariaLabel="Dashboard"
    tabs={[
      { id: 'overview', label: 'Overview', href: '/', content: <DashboardPage /> },
      { id: 'financial', label: 'Financial', href: '/dashboard/financial', content: <FinancialDashboardPage /> },
      { id: 'analytics', label: 'Analytics', href: '/dashboard/analytics', content: <AnalyticsPage /> },
      { id: 'reports', label: 'Reports', href: '/dashboard/reports', content: <ReportsPage /> },
      { id: 'sla', label: 'SLA', href: '/dashboard/sla', content: <SlaDashboardPage /> },
    ]}
  />
);

export default DashboardHubPage;
