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
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';

interface AppNavigationProps {
  children: React.ReactNode;
}

const AppNavigation: React.FC<AppNavigationProps> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { mode, toggleMode } = useTheme();
  const { getNavigationOpen, setNavigationOpen: persistNavOpen, getPinnedOffices } = usePreferences();
  const { settings } = useSiteSettings();

  const [navigationOpen, setNavigationOpen] = useState(() => getNavigationOpen());
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

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
  useKeyboardShortcuts(onShowShortcuts);

  const isEditorOrAdmin = user?.role === 'admin' || user?.role === 'editor';
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
      items: [
        { type: 'link' as const, text: 'Offices', href: '/offices' },
        { type: 'link' as const, text: 'Leases', href: '/leases' },
        { type: 'link' as const, text: 'Landlords', href: '/landlords' },
        { type: 'link' as const, text: 'Property Management', href: '/management-companies' },
        { type: 'link' as const, text: 'Space Management', href: '/space' },
      ],
    },
    {
      type: 'link' as const,
      text: 'Finance',
      href: '/finance',
    },
    {
      type: 'section' as const,
      text: 'Operations',
      items: [
        { type: 'link' as const, text: 'Maintenance Tickets', href: '/maintenance-tickets' },
        { type: 'link' as const, text: 'Vendors', href: '/vendors' },
        { type: 'link' as const, text: 'Transitions', href: '/transitions' },
        { type: 'link' as const, text: 'HVAC', href: '/hvac' },
        ...(isEditorOrAdmin ? [{ type: 'link' as const, text: 'Insurance Certificates', href: '/insurance-certificates' }] : []),
      ],
    },
    ...(isEditorOrAdmin ? [{
      type: 'link' as const,
      text: 'Administration',
      href: '/administration',
    }] : []),
    {
      type: 'link' as const,
      text: 'Self-Service Portal',
      href: '/ticket-portal',
    },
    {
      type: 'link' as const,
      text: 'Settings',
      href: '/settings',
    },
  ], [isEditorOrAdmin, pinnedOffices]);

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
          <SideNavigation
            activeHref={location.pathname}
            header={{ href: '/', text: settings.app_name }}
            items={navItems}
            onFollow={(e) => {
              e.preventDefault();
              navigate(e.detail.href);
            }}
          />
        }
        navigationOpen={navigationOpen}
        onNavigationChange={handleNavigationChange}
        toolsHide
        content={children}
        headerSelector="#top-nav"
      />
      <KeyboardShortcutsModal
        visible={shortcutsOpen}
        onDismiss={() => setShortcutsOpen(false)}
      />
    </>
  );
};

export default AppNavigation;
