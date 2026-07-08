import React from 'react';
import { useAuth } from '@/auth/AuthContext';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';
import LeasingUnitsPage from '@/pages/LeasingUnitsPage';
import ResidentsPage from '@/pages/ResidentsPage';
import ResidentLeasesPage from '@/pages/ResidentLeasesPage';
import LeaseTemplatesPage from '@/pages/LeaseTemplatesPage';
import ApplicationTemplatesPage from '@/pages/ApplicationTemplatesPage';
import RentCollectionPage from '@/pages/RentCollectionPage';
import LeasingFunnelPage from '@/pages/LeasingFunnelPage';
import VacancyListingsPage from '@/pages/VacancyListingsPage';
import AnnouncementsPage from '@/pages/AnnouncementsPage';
import OwnersPage from '@/pages/OwnersPage';

/**
 * "Residential" hub that surfaces the Buildium-parity property-management
 * features as URL-driven tabs, mirroring the FinancePage pattern.
 */
const ResidentialPage: React.FC = () => {
  const { user } = useAuth();
  const isFinance = user?.role === 'admin' || user?.role === 'accountant';

  const tabs: TabbedPageTab[] = [
    { id: 'units', label: 'Units', href: '/residential', content: <LeasingUnitsPage /> },
    {
      id: 'residents',
      label: 'Residents',
      href: '/residential/residents',
      content: <ResidentsPage />,
    },
    {
      id: 'leases',
      label: 'Leases',
      href: '/residential/leases',
      content: <ResidentLeasesPage />,
    },
    {
      id: 'templates',
      label: 'Lease templates',
      href: '/residential/templates',
      content: <LeaseTemplatesPage />,
    },
    {
      id: 'application-templates',
      label: 'Application templates',
      href: '/residential/application-templates',
      content: <ApplicationTemplatesPage />,
    },
    {
      id: 'applications',
      label: 'Applications',
      href: '/residential/applications',
      content: <LeasingFunnelPage />,
    },
    {
      id: 'listings',
      label: 'Listings',
      href: '/residential/listings',
      content: <VacancyListingsPage />,
    },
    {
      id: 'announcements',
      label: 'Announcements',
      href: '/residential/announcements',
      content: <AnnouncementsPage />,
    },
    ...(isFinance
      ? [
          {
            id: 'rent',
            label: 'Rent',
            href: '/residential/rent',
            content: <RentCollectionPage />,
          },
          {
            id: 'owners',
            label: 'Owners',
            href: '/residential/owners',
            content: <OwnersPage />,
          },
        ]
      : []),
  ];

  return <TabbedPage ariaLabel="Residential" tabs={tabs} />;
};

export default ResidentialPage;
