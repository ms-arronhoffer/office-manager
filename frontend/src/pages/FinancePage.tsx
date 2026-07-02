import React from 'react';
import { useAuth } from '@/auth/AuthContext';
import TabbedPage, { TabbedPageTab } from '@/components/layout/TabbedPage';
import RentRollPage from '@/pages/RentRollPage';
import OperatingExpensesPage from '@/pages/OperatingExpensesPage';
import GeneralLedgerPage from '@/pages/GeneralLedgerPage';
import FinancialStatementsPage from '@/pages/FinancialStatementsPage';
import CamReconciliationsPage from '@/pages/CamReconciliationsPage';
import AccountsPayablePage from '@/pages/AccountsPayablePage';
import AccountsReceivablePage from '@/pages/AccountsReceivablePage';
import BankReconciliationPage from '@/pages/BankReconciliationPage';
import Tax1099Page from '@/pages/Tax1099Page';
import LeaseLifecyclePage from '@/pages/LeaseLifecyclePage';

/**
 * Finance hub — merges the operational finance tools (Rent Roll, Operating
 * Expenses, General Ledger) and the audit-grade accounting surface (Financial
 * Statements, CAM, Accounts Payable, Lease Lifecycle) into a single tabbed
 * destination.
 *
 * The executive Financial Dashboard and Reports now live in the Dashboard hub.
 *
 * Role-gated tabs are hidden (not just route-guarded) so users never see an
 * empty panel: Operating Expenses requires admin/editor and the accounting tabs
 * require admin/accountant, matching the route guards in `App.tsx`.
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
      ? [
          { id: 'general-ledger', label: 'General Ledger', href: '/finance/general-ledger', content: <GeneralLedgerPage /> },
          { id: 'financial-statements', label: 'Financial Statements', href: '/finance/financial-statements', content: <FinancialStatementsPage /> },
          { id: 'cam', label: 'CAM', href: '/finance/cam', content: <CamReconciliationsPage /> },
          { id: 'accounts-payable', label: 'Accounts Payable', href: '/finance/accounts-payable', content: <AccountsPayablePage /> },
          { id: 'accounts-receivable', label: 'Accounts Receivable', href: '/finance/accounts-receivable', content: <AccountsReceivablePage /> },
          { id: 'bank-reconciliation', label: 'Bank Reconciliation', href: '/finance/bank-reconciliation', content: <BankReconciliationPage /> },
          { id: 'tax-1099', label: 'Tax / 1099', href: '/finance/tax-1099', content: <Tax1099Page /> },
          { id: 'lease-lifecycle', label: 'Lease Lifecycle', href: '/finance/lease-lifecycle', content: <LeaseLifecyclePage /> },
        ]
      : []),
  ];

  return <TabbedPage ariaLabel="Finance" tabs={tabs} />;
};

export default FinancePage;
