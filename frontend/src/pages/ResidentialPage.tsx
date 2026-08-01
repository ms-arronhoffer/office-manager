import React from 'react';
import { useAuth } from '@/auth/AuthContext';
import GroupedTabbedPage, { TabGroup } from '@/components/layout/GroupedTabbedPage';
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
 * Residential hub — the ten residential surfaces grouped by the stage of the
 * tenancy they belong to, so related records sit together instead of competing
 * as peer tabs. Tab URLs are unchanged.
 */
const ResidentialPage: React.FC = () => {
  const { user } = useAuth();
  const isFinance = user?.role === 'admin' || user?.role === 'accountant';

  const groups: TabGroup[] = [
    {
      id: 'units',
      label: 'Units & occupancy',
      tabs: [
        { id: 'units', label: 'Units', href: '/residential', content: <LeasingUnitsPage /> },
        {
          id: 'listings',
          label: 'Listings',
          href: '/residential/listings',
          content: <VacancyListingsPage />,
        },
      ],
    },
    {
      id: 'residents',
      label: 'Residents & leases',
      tabs: [
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
          id: 'announcements',
          label: 'Announcements',
          href: '/residential/announcements',
          content: <AnnouncementsPage />,
        },
      ],
    },
    {
      id: 'applications',
      label: 'Applications',
      tabs: [
        {
          id: 'applications',
          label: 'Applications',
          href: '/residential/applications',
          content: <LeasingFunnelPage />,
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
      ],
    },
    {
      id: 'finance',
      label: 'Finance',
      tabs: isFinance
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
        : [],
    },
  ];

  return <GroupedTabbedPage ariaLabel="Residential" groups={groups} />;
};

export default ResidentialPage;
