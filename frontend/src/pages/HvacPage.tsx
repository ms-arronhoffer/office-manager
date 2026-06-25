import React from 'react';
import TabbedPage from '@/components/layout/TabbedPage';
import HqHvacPage from '@/pages/HqHvacPage';
import HvacContractsPage from '@/pages/HvacContractsPage';

/**
 * HVAC hub — merges the former "HVAC Systems" and "HVAC Contracts" nav links
 * into a single destination with in-page tabs.
 */
const HvacPage: React.FC = () => (
  <TabbedPage
    ariaLabel="HVAC"
    tabs={[
      { id: 'systems', label: 'Systems', href: '/hvac', content: <HqHvacPage /> },
      { id: 'contracts', label: 'Contracts', href: '/hvac/contracts', content: <HvacContractsPage /> },
    ]}
  />
);

export default HvacPage;
