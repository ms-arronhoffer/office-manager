import React, { useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import FormField from '@cloudscape-design/components/form-field';
import Tiles from '@cloudscape-design/components/tiles';
import Toggle from '@cloudscape-design/components/toggle';
import Box from '@cloudscape-design/components/box';
import Link from '@cloudscape-design/components/link';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import { useTheme } from '@/theme/ThemeContext';
import { usePreferences } from '@/context/PreferencesContext';
import { useAuth } from '@/auth/AuthContext';
import { auth as authApi } from '@/api';
import DashboardSettingsModal, { type DashboardWidget } from '@/components/dashboard/DashboardSettingsModal';

const DASHBOARD_WIDGETS: DashboardWidget[] = [
  { id: 'stat_cards', label: 'Summary Statistics' },
  { id: 'tickets_table', label: 'Open & In Progress Tickets' },
  { id: 'lease_chart', label: 'Lease Expirations Chart' },
  { id: 'hvac_table', label: 'Upcoming HVAC Services' },
  { id: 'transitions_table', label: 'Active Transitions' },
  { id: 'activity_feed', label: 'Recent Activity' },
];

const SettingsPage: React.FC = () => {
  const { mode, toggleMode, density, setDensity, fontSize, setFontSize } = useTheme();
  const { getDashboardWidgets, setDashboardWidget } = usePreferences();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const widgetVisibility = getDashboardWidgets();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [pwdSaving, setPwdSaving] = useState(false);
  const [pwdError, setPwdError] = useState<string | null>(null);
  const [pwdSuccess, setPwdSuccess] = useState(false);

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      setPwdError('New passwords do not match.');
      return;
    }
    if (newPassword.length < 8) {
      setPwdError('New password must be at least 8 characters.');
      return;
    }
    setPwdSaving(true);
    setPwdError(null);
    setPwdSuccess(false);
    try {
      await authApi.changePassword(currentPassword, newPassword);
      setPwdSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setPwdError(detail || 'Failed to change password.');
    } finally {
      setPwdSaving(false);
    }
  };

  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <SpaceBetween size="l">
        {/* Appearance */}
        <Container header={<Header variant="h2">Appearance</Header>}>
          <SpaceBetween size="l">
            <FormField label="Theme" description="Choose between light and dark mode">
              <Tiles
                value={mode}
                onChange={({ detail }) => {
                  if (detail.value !== mode) toggleMode();
                }}
                items={[
                  { value: 'light', label: 'Light', description: 'Light background with dark text' },
                  { value: 'dark', label: 'Dark', description: 'Dark background with light text' },
                ]}
              />
            </FormField>

            <FormField label="Density" description="Adjust spacing between UI elements">
              <Tiles
                value={density}
                onChange={({ detail }) => setDensity(detail.value as 'comfortable' | 'compact')}
                items={[
                  { value: 'comfortable', label: 'Comfortable', description: 'Default spacing' },
                  { value: 'compact', label: 'Compact', description: 'Reduced spacing for more content' },
                ]}
              />
            </FormField>

            <FormField label="Font size" description="Adjust the text size across the application">
              <Tiles
                value={fontSize}
                onChange={({ detail }) => setFontSize(detail.value as 'small' | 'medium' | 'large')}
                items={[
                  { value: 'small', label: 'Small' },
                  { value: 'medium', label: 'Medium' },
                  { value: 'large', label: 'Large' },
                ]}
              />
            </FormField>
          </SpaceBetween>
        </Container>

        {/* Dashboard Layout */}
        <Container header={<Header variant="h2">Dashboard Layout</Header>}>
          <SpaceBetween size="m">
            <Box variant="p" color="text-body-secondary">
              Choose which sections to display on your dashboard.
            </Box>
            {DASHBOARD_WIDGETS.map((widget) => (
              <Toggle
                key={widget.id}
                checked={widgetVisibility[widget.id] !== false}
                onChange={({ detail }) => setDashboardWidget(widget.id, detail.checked)}
              >
                {widget.label}
              </Toggle>
            ))}
          </SpaceBetween>
        </Container>

        {/* Notifications */}
        <Container header={<Header variant="h2">Notifications</Header>}>
          <SpaceBetween size="s">
            <Box variant="p" color="text-body-secondary">
              Email notification rules control when and how alerts are sent for lease expirations,
              HVAC service reminders, and high-priority maintenance tickets.
            </Box>
            {isAdmin ? (
              <Link href="/email-rules">Manage email notification rules</Link>
            ) : (
              <Box variant="p">
                Contact your administrator to configure email notification rules.
              </Box>
            )}
          </SpaceBetween>
        </Container>

        {/* Saved Filters */}
        <Container header={<Header variant="h2">Saved Filters</Header>}>
          <Box variant="p" color="text-body-secondary">
            You can save and manage filter presets directly from list pages (Offices, Leases, Maintenance Tickets).
            Use the &quot;Saved filters&quot; dropdown next to the filter bar on any list page.
          </Box>
        </Container>

        {/* Change Password — internal accounts only */}
        {user?.auth_provider === 'internal' && (
          <Container header={<Header variant="h2">Change Password</Header>}>
            <SpaceBetween size="m">
              {pwdError && (
                <Alert type="error" dismissible onDismiss={() => setPwdError(null)}>{pwdError}</Alert>
              )}
              {pwdSuccess && (
                <Alert type="success" dismissible onDismiss={() => setPwdSuccess(false)}>Password changed successfully.</Alert>
              )}
              <FormField label="Current Password">
                <Input
                  type="password"
                  value={currentPassword}
                  onChange={({ detail }) => setCurrentPassword(detail.value)}
                  placeholder="Enter current password"
                />
              </FormField>
              <FormField label="New Password">
                <Input
                  type="password"
                  value={newPassword}
                  onChange={({ detail }) => setNewPassword(detail.value)}
                  placeholder="At least 8 characters"
                />
              </FormField>
              <FormField label="Confirm New Password">
                <Input
                  type="password"
                  value={confirmPassword}
                  onChange={({ detail }) => setConfirmPassword(detail.value)}
                  placeholder="Repeat new password"
                />
              </FormField>
              <Button
                variant="primary"
                loading={pwdSaving}
                disabled={!currentPassword || !newPassword || !confirmPassword}
                onClick={handleChangePassword}
              >
                Change Password
              </Button>
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default SettingsPage;
