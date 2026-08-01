import React from 'react';
import { useAuth } from '@/auth/AuthContext';
import FeatureUnavailable from '@/components/common/FeatureUnavailable';
import GroupedTabbedPage, { TabGroup } from '@/components/layout/GroupedTabbedPage';
import RentRollPage from '@/pages/RentRollPage';
import OperatingExpensesPage from '@/pages/OperatingExpensesPage';
import GeneralLedgerPage from '@/pages/GeneralLedgerPage';
import FinancialStatementsPage from '@/pages/FinancialStatementsPage';
import CamReconciliationsPage from '@/pages/CamReconciliationsPage';
import AccountsPayablePage from '@/pages/AccountsPayablePage';
import AccountsReceivablePage from '@/pages/AccountsReceivablePage';
import BankReconciliationPage from '@/pages/BankReconciliationPage';
import Tax1099Page from '@/pages/Tax1099Page';
import BudgetingPage from '@/pages/BudgetingPage';
import LeaseLifecyclePage from '@/pages/LeaseLifecyclePage';

/**
 * Finance hub — the eleven finance surfaces grouped into the four jobs an
 * operator actually works in (money in, money out, lease accounting, and
 * reporting) instead of one flat strip of peer tabs.
 *
 * Every tab keeps its original URL, so existing links and the route guards in
 * `App.tsx` are unaffected. Role-gated tabs are hidden rather than rendered
 * empty, and a user left with nothing gets an explanation instead of a blank
 * panel.
 */
const FinancePage: React.FC = () => {
  const { user } = useAuth();
  const isEditorOrAdmin = user?.role === 'admin' || user?.role === 'editor';
  const isFinance = user?.role === 'admin' || user?.role === 'accountant';

  const groups: TabGroup[] = [
    {
      id: 'cash',
      label: 'Cash',
      tabs: [
        { id: 'rent-roll', label: 'Rent Roll', href: '/finance', content: <RentRollPage /> },
        ...(isFinance
          ? [
              {
                id: 'accounts-receivable',
                label: 'Accounts Receivable',
                href: '/finance/accounts-receivable',
                content: <AccountsReceivablePage />,
              },
            ]
          : []),
      ],
    },
    {
      id: 'expenses',
      label: 'Expenses',
      tabs: [
        ...(isEditorOrAdmin
          ? [
              {
                id: 'operating-expenses',
                label: 'Operating Expenses',
                href: '/finance/operating-expenses',
                content: <OperatingExpensesPage />,
              },
            ]
          : []),
        ...(isFinance
          ? [
              {
                id: 'accounts-payable',
                label: 'Accounts Payable',
                href: '/finance/accounts-payable',
                content: <AccountsPayablePage />,
              },
              {
                id: 'bank-reconciliation',
                label: 'Bank Reconciliation',
                href: '/finance/bank-reconciliation',
                content: <BankReconciliationPage />,
              },
            ]
          : []),
      ],
    },
    {
      id: 'lease-accounting',
      label: 'Lease accounting',
      tabs: isFinance
        ? [
            { id: 'cam', label: 'CAM', href: '/finance/cam', content: <CamReconciliationsPage /> },
            {
              id: 'lease-lifecycle',
              label: 'Lease Lifecycle',
              href: '/finance/lease-lifecycle',
              content: <LeaseLifecyclePage />,
            },
            {
              id: 'general-ledger',
              label: 'General Ledger',
              href: '/finance/general-ledger',
              content: <GeneralLedgerPage />,
            },
          ]
        : [],
    },
    {
      id: 'reporting',
      label: 'Reporting',
      tabs: isFinance
        ? [
            {
              id: 'financial-statements',
              label: 'Financial Statements',
              href: '/finance/financial-statements',
              content: <FinancialStatementsPage />,
            },
            {
              id: 'budgeting',
              label: 'Budgeting',
              href: '/finance/budgeting',
              content: <BudgetingPage />,
            },
            {
              id: 'tax-1099',
              label: 'Tax / 1099',
              href: '/finance/tax-1099',
              content: <Tax1099Page />,
            },
          ]
        : [],
    },
  ];

  return (
    <GroupedTabbedPage
      ariaLabel="Finance"
      groups={groups}
      emptyState={
        <FeatureUnavailable
          featureName="Finance"
          reason="role"
          allowedRoles={['admin', 'accountant', 'editor']}
        />
      }
    />
  );
};

export default FinancePage;
