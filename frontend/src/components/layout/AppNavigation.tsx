import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import AppLayout from '@cloudscape-design/components/app-layout';
import SideNavigation from '@cloudscape-design/components/side-navigation';
import TopNavigation from '@cloudscape-design/components/top-navigation';
import { useAuth } from '@/auth/AuthContext';
import { useTheme } from '@/theme/ThemeContext';
import { usePreferences } from '@/context/PreferencesContext';
import { useSiteSettings } from '@/context/SiteSettingsContext';
import GlobalSearchBar from '@/components/common/GlobalSearchBar';
import KeyboardShortcutsModal from '@/components/common/KeyboardShortcutsModal';
import NotificationBell from '@/components/common/NotificationBell';
import SupportRequestModal from '@/components/common/SupportRequestModal';
import AIPortfolioAssistant from '@/components/common/AIPortfolioAssistant';
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';
import { useInstallPrompt } from '@/hooks/useInstallPrompt';
import './AppNavigation.css';

interface AppNavigationProps {
  children: React.ReactNode;
}

const AI_ASSISTANT_DRAWER_ID = 'ai-portfolio-assistant';

const AppNavigation: React.FC<AppNavigationProps> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { mode, toggleMode } = useTheme();
  const { getNavigationOpen, setNavigationOpen: persistNavOpen, getPinnedOffices } = usePreferences();
  const { settings } = useSiteSettings();

  const [navigationOpen, setNavigationOpen] = useState(() => getNavigationOpen());
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [supportOpen, setSupportOpen] = useState(false);
  const [activeDrawerId, setActiveDrawerId] = useState<string | null>(null);

  // Sync sidebar state from prefs on load
  useEffect(() => {
    setNavigationOpen(getNavigationOpen());
  }, [getNavigationOpen]);

  const handleNavigationChange = useCallback(({ detail }: { detail: { open: boolean } }) => {
    setNavigationOpen(detail.open);
    persistNavOpen(detail.open);
  }, [persistNavOpen]);

  // Keyboard shortcuts
  const onShowShortcuts = useCallback(() => setShortcutsOpen(true), []);
  const toggleAssistant = useCallback(
    () => setActiveDrawerId((id) => (id === AI_ASSISTANT_DRAWER_ID ? null : AI_ASSISTANT_DRAWER_ID)),
    [],
  );
  useKeyboardShortcuts(onShowShortcuts, toggleAssistant);
  const { canInstall, promptInstall } = useInstallPrompt();

  const isEditorOrAdmin = user?.role === 'admin' || user?.role === 'editor';
  const isFinance = user?.role === 'admin' || user?.role === 'accountant';
  const isSuperAdmin = user?.is_super_admin === true;
  const pinnedOffices = getPinnedOffices();

  const navItems = useMemo(() => [
    {
      type: 'link' as const,
      text: 'Dashboard',
      href: '/',
    },
    ...(pinnedOffices.length > 0
      ? [{
          type: 'section' as const,
          text: 'Pinned Offices',
          defaultExpanded: false,
          items: pinnedOffices.map((o) => ({
            type: 'link' as const,
            text: o.label,
            href: `/offices/${o.id}`,
          })),
        }]
      : []),
    {
      type: 'section' as const,
      text: 'Portfolio',
      defaultExpanded: false,
      items: [
        { type: 'link' as const, text: 'Offices', href: '/offices' },
        { type: 'link' as const, text: 'Leases', href: '/leases' },
        { type: 'link' as const, text: 'Landlords', href: '/landlords' },
        { type: 'link' as const, text: 'Property Management', href: '/management-companies' },
        { type: 'link' as const, text: 'Space Management', href: '/space' },
      ],
    },
    {
      type: 'section' as const,
      text: 'Residential',
      defaultExpanded: false,
      items: [
        { type: 'link' as const, text: 'Units', href: '/residential' },
        { type: 'link' as const, text: 'Residents', href: '/residential/residents' },
        { type: 'link' as const, text: 'Resident Leases', href: '/residential/leases' },
        { type: 'link' as const, text: 'Lease Templates', href: '/residential/templates' },
        { type: 'link' as const, text: 'Application Templates', href: '/residential/application-templates' },
        { type: 'link' as const, text: 'Applications & Screening', href: '/residential/applications' },
        { type: 'link' as const, text: 'Vacancy Listings', href: '/residential/listings' },
        { type: 'link' as const, text: 'Announcements', href: '/residential/announcements' },
        ...(isFinance
          ? [
              { type: 'link' as const, text: 'Rent Collection', href: '/residential/rent' },
              { type: 'link' as const, text: 'Owners & Trust', href: '/residential/owners' },
            ]
          : []),
      ],
    },
    {
      type: 'section' as const,
      text: 'Operations',
      defaultExpanded: false,
      items: [
        { type: 'link' as const, text: 'Maintenance Tickets', href: '/maintenance-tickets' },
        { type: 'link' as const, text: 'Inspections', href: '/inspections' },
        { type: 'link' as const, text: 'Vendors', href: '/vendors' },
        { type: 'link' as const, text: 'Transitions', href: '/transitions' },
        ...(isEditorOrAdmin ? [{ type: 'link' as const, text: 'Insurance Certificates', href: '/insurance-certificates' }] : []),
        ...(isEditorOrAdmin ? [{ type: 'link' as const, text: 'Digital Waivers', href: '/waivers' }] : []),
      ],
    },
    {
      type: 'section' as const,
      text: 'Maintenance',
      defaultExpanded: false,
      items: [
        { type: 'link' as const, text: 'Overview', href: '/maintenance' },
        { type: 'link' as const, text: 'HVAC Systems', href: '/maintenance/hvac' },
        { type: 'link' as const, text: 'Fire & Life Safety', href: '/maintenance/fire_life_safety' },
        { type: 'link' as const, text: 'Plumbing & Backflow', href: '/maintenance/plumbing_backflow' },
        { type: 'link' as const, text: 'Refuse & Waste', href: '/maintenance/refuse_waste' },
        { type: 'link' as const, text: 'Exterior & Structural', href: '/maintenance/exterior_structural' },
        { type: 'link' as const, text: 'Elevators & Lifts', href: '/maintenance/elevators_lifts' },
      ],
    },
    {
      type: 'section' as const,
      text: 'Finance',
      defaultExpanded: false,
      items: [
        { type: 'link' as const, text: 'Rent Roll', href: '/finance' },
        ...(isEditorOrAdmin ? [{ type: 'link' as const, text: 'Operating Expenses', href: '/finance/operating-expenses' }] : []),
        ...(isFinance ? [
          { type: 'link' as const, text: 'General Ledger', href: '/finance/general-ledger' },
          { type: 'link' as const, text: 'Financial Statements', href: '/finance/financial-statements' },
          { type: 'link' as const, text: 'CAM', href: '/finance/cam' },
          { type: 'link' as const, text: 'Accounts Payable', href: '/finance/accounts-payable' },
          { type: 'link' as const, text: 'Accounts Receivable', href: '/finance/accounts-receivable' },
          { type: 'link' as const, text: 'Bank Reconciliation', href: '/finance/bank-reconciliation' },
          { type: 'link' as const, text: 'Budgeting', href: '/finance/budgeting' },
          { type: 'link' as const, text: 'Tax / 1099', href: '/finance/tax-1099' },
          { type: 'link' as const, text: 'Lease Lifecycle', href: '/finance/lease-lifecycle' },
        ] : []),
      ],
    },
    ...(isEditorOrAdmin ? [{
      type: 'link' as const,
      text: 'Administration',
      href: '/administration',
    }] : []),
    ...(isSuperAdmin ? [{
      type: 'link' as const,
      text: 'Platform',
      href: '/platform',
    }] : []),
    {
      type: 'link' as const,
      text: 'Settings',
      href: '/settings',
    },
  ], [isEditorOrAdmin, isFinance, isSuperAdmin, pinnedOffices]);

  return (
    <>
      <div id="top-nav" style={{ position: 'sticky', top: 0, zIndex: 1002 }}>
        <TopNavigation
          identity={{
            href: '/',
            title: settings.app_name,
            onFollow: (e) => {
              e.preventDefault();
              navigate('/');
            },
          }}
          search={<GlobalSearchBar />}
          utilities={[
            ...(canInstall
              ? [
                  {
                    type: 'button' as const,
                    iconName: 'download' as const,
                    text: 'Install app',
                    title: 'Install Portfolio Desk as an app',
                    ariaLabel: 'Install Portfolio Desk as an app',
                    onClick: promptInstall,
                  },
                ]
              : []),
            {
              type: 'button',
              iconName: 'support',
              text: 'Support',
              title: 'Submit a support request',
              ariaLabel: 'Submit a support request',
              onClick: () => setSupportOpen(true),
            },
            {
              type: 'button',
              iconName: mode === 'dark' ? 'status-positive' : 'status-negative',
              title: mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode',
              ariaLabel: mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode',
              onClick: toggleMode,
            },
            {
              type: 'menu-dropdown',
              text: user?.display_name || user?.email || 'User',
              description: user?.email,
              iconName: 'user-profile',
              items: [
                {
                  id: 'profile',
                  text: 'Profile',
                  iconName: 'user-profile',
                },
                {
                  id: 'settings',
                  text: 'Settings',
                },
                {
                  id: 'divider',
                  text: '-',
                },
                {
                  id: 'signout',
                  text: 'Sign out',
                  iconName: 'close',
                },
              ],
              onItemClick: ({ detail }) => {
                if (detail.id === 'signout') {
                  logout();
                } else if (detail.id === 'settings') {
                  navigate('/settings');
                }
              },
            },
          ]}
        />
        {/* Notification bell — positioned inside the sticky nav bar */}
        <div style={{ position: 'absolute', top: 0, right: 170, height: '100%', display: 'flex', alignItems: 'center', zIndex: 1003 }}>
          <NotificationBell />
        </div>
      </div>
      <AppLayout
        navigation={
          <div className="app-side-nav">
            <SideNavigation
              activeHref={location.pathname}
              header={{ href: '/', text: settings.app_name }}
              items={navItems}
              onFollow={(e) => {
                e.preventDefault();
                navigate(e.detail.href);
              }}
            />
          </div>
        }
        navigationOpen={navigationOpen}
        onNavigationChange={handleNavigationChange}
        drawers={[
          {
            id: AI_ASSISTANT_DRAWER_ID,
            content: <AIPortfolioAssistant />,
            trigger: { iconName: 'gen-ai' },
            ariaLabels: {
              drawerName: 'AI portfolio assistant',
              closeButton: 'Close AI portfolio assistant',
              triggerButton: 'Open AI portfolio assistant',
              resizeHandle: 'Resize AI portfolio assistant',
            },
            resizable: true,
            defaultSize: 420,
            preserveInactiveContent: true,
          },
        ]}
        activeDrawerId={activeDrawerId}
        onDrawerChange={({ detail }) => setActiveDrawerId(detail.activeDrawerId)}
        content={children}
        headerSelector="#top-nav"
      />
      <KeyboardShortcutsModal
        visible={shortcutsOpen}
        onDismiss={() => setShortcutsOpen(false)}
      />
      <SupportRequestModal
        visible={supportOpen}
        onDismiss={() => setSupportOpen(false)}
      />
    </>
  );
};

export default AppNavigation;
