import React from 'react';
import { useAuth } from '@/auth/AuthContext';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';
import RentRollPage from '@/pages/RentRollPage';
import OperatingExpensesPage from '@/pages/OperatingExpensesPage';
import GeneralLedgerPage from '@/pages/GeneralLedgerPage';

/**
 * Finance hub — merges the operational finance tools (Rent Roll, Operating
 * Expenses, General Ledger) into a single tabbed destination.
 *
 * The executive Financial Dashboard and Reports now live in the Dashboard hub.
 *
 * Role-gated tabs are hidden (not just route-guarded) so users never see an
 * empty panel: Operating Expenses requires admin/editor and General Ledger
 * requires admin/accountant, matching the route guards in `App.tsx`.
 */
const FinancePage: React.FC = () => {
  const { user } = useAuth();
  const isEditorOrAdmin = user?.role === 'admin' || user?.role === 'editor';
  const isFinance = user?.role === 'admin' || user?.role === 'accountant';

  const tabs: TabbedPageTab[] = [
    { id: 'rent-roll', label: 'Rent Roll', href: '/finance', content: <RentRollPage /> },
    ...(isEditorOrAdmin
      ? [{ id: 'operating-expenses', label: 'Operating Expenses', href: '/finance/operating-expenses', content: <OperatingExpensesPage /> }]
      : []),
    ...(isFinance
      ? [{ id: 'general-ledger', label: 'General Ledger', href: '/finance/general-ledger', content: <GeneralLedgerPage /> }]
      : []),
  ];

  return <TabbedPage ariaLabel="Finance" tabs={tabs} />;
};

export default FinancePage;
