import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Spinner from '@cloudscape-design/components/spinner';
import Box from '@cloudscape-design/components/box';
import { AuthProvider } from '@/auth/AuthContext';
import { PreferencesProvider } from '@/context/PreferencesContext';
import { FlashbarProvider } from '@/context/FlashbarContext';
import { SiteSettingsProvider } from '@/context/SiteSettingsContext';
import { ThemeProvider } from '@/theme/ThemeContext';
import { WSProvider } from '@/context/WSContext';
import ProtectedRoute from '@/auth/ProtectedRoute';
import RoleGuard from '@/auth/RoleGuard';
import SuperAdminGuard from '@/auth/SuperAdminGuard';
import AppNavigation from '@/components/layout/AppNavigation';
import SessionTimeoutWarning from '@/components/common/SessionTimeoutWarning';

// Lazy-loaded pages
const LoginPage = lazy(() => import('@/pages/LoginPage'));
const SignupPage = lazy(() => import('@/pages/SignupPage'));
const OnboardingPage = lazy(() => import('@/pages/OnboardingPage'));
const BillingPage = lazy(() => import('@/pages/BillingPage'));
const ApiKeysPage = lazy(() => import('@/pages/ApiKeysPage'));
const WebhooksPage = lazy(() => import('@/pages/WebhooksPage'));
const OfficesPage = lazy(() => import('@/pages/OfficesPage'));
const OfficeDetailPage = lazy(() => import('@/pages/OfficeDetailPage'));
const OfficeFormPage = lazy(() => import('@/pages/OfficeFormPage'));
const LeasesPage = lazy(() => import('@/pages/LeasesPage'));
const LeaseDetailPage = lazy(() => import('@/pages/LeaseDetailPage'));
const LeaseFormPage = lazy(() => import('@/pages/LeaseFormPage'));
const LandlordsPage = lazy(() => import('@/pages/LandlordsPage'));
const LandlordDetailPage = lazy(() => import('@/pages/LandlordDetailPage'));
const LandlordFormPage = lazy(() => import('@/pages/LandlordFormPage'));
const TransitionsPage = lazy(() => import('@/pages/TransitionsPage'));
const TransitionDetailPage = lazy(() => import('@/pages/TransitionDetailPage'));
const TransitionFormPage = lazy(() => import('@/pages/TransitionFormPage'));
const HvacContractDetailPage = lazy(() => import('@/pages/HvacContractDetailPage'));
const HvacContractFormPage = lazy(() => import('@/pages/HvacContractFormPage'));
const ManagersPage = lazy(() => import('@/pages/ManagersPage'));
const TicketCategoriesPage = lazy(() => import('@/pages/TicketCategoriesPage'));
const MaintenanceTopicsPage = lazy(() => import('@/pages/MaintenanceTopicsPage'));
const MaintenanceTicketsPage = lazy(() => import('@/pages/MaintenanceTicketsPage'));
const MaintenanceTicketFormPage = lazy(() => import('@/pages/MaintenanceTicketFormPage'));
const MaintenanceTicketDetailPage = lazy(() => import('@/pages/MaintenanceTicketDetailPage'));
const UsersPage = lazy(() => import('@/pages/UsersPage'));
const VendorsPage = lazy(() => import('@/pages/VendorsPage'));
const VendorFormPage = lazy(() => import('@/pages/VendorFormPage'));
const VendorDetailPage = lazy(() => import('@/pages/VendorDetailPage'));
const ManagementCompaniesPage = lazy(() => import('@/pages/ManagementCompaniesPage'));
const ManagementCompanyDetailPage = lazy(() => import('@/pages/ManagementCompanyDetailPage'));
const ManagementCompanyFormPage = lazy(() => import('@/pages/ManagementCompanyFormPage'));
const DataDictionaryPage = lazy(() => import('@/pages/DataDictionaryPage'));
const EmailRulesPage = lazy(() => import('@/pages/EmailRulesPage'));
const WaiversPage = lazy(() => import('@/pages/WaiversPage'));
const WaiverSignPage = lazy(() => import('@/pages/WaiverSignPage'));
const AckPage = lazy(() => import('@/pages/AckPage'));
const SettingsPage = lazy(() => import('@/pages/SettingsPage'));
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'));
const ActivityLogPage = lazy(() => import('@/pages/ActivityLogPage'));
const TrashPage = lazy(() => import('@/pages/TrashPage'));
const SiteSettingsPage = lazy(() => import('@/pages/SiteSettingsPage'));
const SupportRequestsPage = lazy(() => import('@/pages/SupportRequestsPage'));
const LeaseCalendarPage = lazy(() => import('@/pages/LeaseCalendarPage'));
const TicketTemplatesPage = lazy(() => import('@/pages/TicketTemplatesPage'));
const RecurringTicketsPage = lazy(() => import('@/pages/RecurringTicketsPage'));
const VendorPortalPage = lazy(() => import('@/pages/VendorPortalPage'));
const ClientPortalPage = lazy(() => import('@/pages/ClientPortalPage'));
const InsuranceCertificatesPage = lazy(() => import('@/pages/InsuranceCertificatesPage'));
const SpacePage = lazy(() => import('@/pages/SpacePage'));
const DashboardHubPage = lazy(() => import('@/pages/DashboardHubPage'));
const FinancePage = lazy(() => import('@/pages/FinancePage'));
const HvacPage = lazy(() => import('@/pages/HvacPage'));
const MaintenancePage = lazy(() => import('@/pages/MaintenancePage'));
const AdministrationPage = lazy(() => import('@/pages/AdministrationPage'));
const PlatformAdminPage = lazy(() => import('@/pages/PlatformAdminPage'));

const PageLoader = () => (
  <Box textAlign="center" padding={{ top: 'xxxl' }}>
    <Spinner size="large" />
  </Box>
);

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <SiteSettingsProvider>
      <AuthProvider>
        <PreferencesProvider>
        <ThemeProvider>
        <FlashbarProvider>
        <WSProvider token={localStorage.getItem('access_token')}>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/vendor-portal" element={<VendorPortalPage />} />
            <Route path="/client-portal" element={<ClientPortalPage />} />
            <Route path="/client-portal/signup" element={<ClientPortalPage />} />
            <Route path="/sign/:token" element={<WaiverSignPage />} />
            <Route path="/ack/:token" element={<AckPage />} />
            <Route
              path="/onboarding"
              element={
                <ProtectedRoute>
                  <OnboardingPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                <SessionTimeoutWarning />
                <AppNavigation>
                    <Suspense fallback={<PageLoader />}>
                      <Routes>
                        <Route index element={<DashboardHubPage />} />
                        <Route path="dashboard/financial" element={<DashboardHubPage />} />
                        <Route path="dashboard/analytics" element={<DashboardHubPage />} />
                        <Route path="dashboard/reports" element={<DashboardHubPage />} />
                        <Route path="dashboard/sla" element={<DashboardHubPage />} />
                        <Route path="offices" element={<OfficesPage />} />
                        <Route path="offices/new" element={<OfficeFormPage />} />
                        <Route path="offices/:id" element={<OfficeDetailPage />} />
                        <Route path="offices/:id/edit" element={<OfficeFormPage />} />
                        <Route path="leases" element={<LeasesPage />} />
                        <Route path="leases/calendar" element={<LeaseCalendarPage />} />
                        <Route path="finance" element={<FinancePage />} />
                        <Route path="finance/operating-expenses" element={<RoleGuard allowedRoles={['admin', 'editor']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/general-ledger" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/financial-statements" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/cam" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/accounts-payable" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/accounts-receivable" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/bank-reconciliation" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/tax-1099" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/budgeting" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/lease-lifecycle" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="leases/new" element={<LeaseFormPage />} />
                        <Route path="leases/:id" element={<LeaseDetailPage />} />
                        <Route path="leases/:id/edit" element={<LeaseFormPage />} />
                        <Route path="landlords" element={<LandlordsPage />} />
                        <Route path="landlords/new" element={<LandlordFormPage />} />
                        <Route path="landlords/:id" element={<LandlordDetailPage />} />
                        <Route path="landlords/:id/edit" element={<LandlordFormPage />} />
                        <Route path="vendors" element={<VendorsPage />} />
                        <Route path="vendors/new" element={<VendorFormPage />} />
                        <Route path="vendors/:id" element={<VendorDetailPage />} />
                        <Route path="vendors/:id/edit" element={<VendorFormPage />} />
                        <Route path="management-companies" element={<ManagementCompaniesPage />} />
                        <Route path="management-companies/new" element={<ManagementCompanyFormPage />} />
                        <Route path="management-companies/:id" element={<ManagementCompanyDetailPage />} />
                        <Route
                          path="management-companies/:id/edit"
                          element={<ManagementCompanyFormPage />}
                        />
                        <Route path="transitions" element={<TransitionsPage />} />
                        <Route path="transitions/new" element={<TransitionFormPage />} />
                        <Route path="transitions/:id" element={<TransitionDetailPage />} />
                        <Route path="transitions/:id/edit" element={<TransitionFormPage />} />
                        <Route path="hvac" element={<HvacPage />} />
                        <Route path="hvac/contracts" element={<HvacPage />} />
                        <Route path="maintenance" element={<MaintenancePage />} />
                        <Route path="maintenance/:category" element={<MaintenancePage />} />
                        <Route path="hvac-contracts/new" element={<HvacContractFormPage />} />
                        <Route path="hvac-contracts/:id" element={<HvacContractDetailPage />} />
                        <Route path="hvac-contracts/:id/edit" element={<HvacContractFormPage />} />
                        <Route path="administration" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
                        <Route path="administration/automation" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
                        <Route path="administration/integrations" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
                        <Route path="administration/system" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
                        <Route path="administration/platform" element={<SuperAdminGuard><AdministrationPage /></SuperAdminGuard>} />
                        <Route path="platform" element={<SuperAdminGuard><PlatformAdminPage /></SuperAdminGuard>} />
                        <Route path="platform/orgs" element={<SuperAdminGuard><PlatformAdminPage /></SuperAdminGuard>} />
                        <Route path="platform/billing" element={<SuperAdminGuard><PlatformAdminPage /></SuperAdminGuard>} />
                        <Route path="platform/usage" element={<SuperAdminGuard><PlatformAdminPage /></SuperAdminGuard>} />
                        <Route path="platform/audit" element={<SuperAdminGuard><PlatformAdminPage /></SuperAdminGuard>} />
                        <Route path="platform/users" element={<SuperAdminGuard><PlatformAdminPage /></SuperAdminGuard>} />
                        <Route path="platform/jobs" element={<SuperAdminGuard><PlatformAdminPage /></SuperAdminGuard>} />
                        <Route path="managers" element={<RoleGuard allowedRoles={['admin']}><ManagersPage /></RoleGuard>} />
                        <Route path="ticket-categories" element={<RoleGuard allowedRoles={['admin']}><TicketCategoriesPage /></RoleGuard>} />
                        <Route path="maintenance-topics" element={<RoleGuard allowedRoles={['admin', 'editor']}><MaintenanceTopicsPage /></RoleGuard>} />
                        <Route path="maintenance-tickets" element={<MaintenanceTicketsPage />} />
                        <Route path="maintenance-tickets/new" element={<MaintenanceTicketFormPage />} />
                        <Route path="maintenance-tickets/:id" element={<MaintenanceTicketDetailPage />} />
                        <Route path="maintenance-tickets/:id/edit" element={<MaintenanceTicketFormPage />} />
                        <Route path="users" element={<RoleGuard allowedRoles={['admin']}><UsersPage /></RoleGuard>} />
                        <Route path="data-dictionary" element={<RoleGuard allowedRoles={['admin']}><DataDictionaryPage /></RoleGuard>} />
                        <Route path="email-rules" element={<RoleGuard allowedRoles={['admin']}><EmailRulesPage /></RoleGuard>} />
                        <Route path="waivers" element={<RoleGuard allowedRoles={['admin', 'editor']}><WaiversPage /></RoleGuard>} />
                        <Route path="settings" element={<SettingsPage />} />
                        <Route path="activity-log" element={<RoleGuard allowedRoles={['admin']}><ActivityLogPage /></RoleGuard>} />
                        <Route path="trash" element={<RoleGuard allowedRoles={['admin']}><TrashPage /></RoleGuard>} />
                        <Route path="admin/site-settings" element={<RoleGuard allowedRoles={['admin']}><SiteSettingsPage /></RoleGuard>} />
                        <Route path="support-requests" element={<RoleGuard allowedRoles={['admin']}><SupportRequestsPage /></RoleGuard>} />
                        <Route path="billing" element={<RoleGuard allowedRoles={['admin']}><BillingPage /></RoleGuard>} />
                        <Route path="api-keys" element={<RoleGuard allowedRoles={['admin']}><ApiKeysPage /></RoleGuard>} />
                        <Route path="webhooks" element={<RoleGuard allowedRoles={['admin']}><WebhooksPage /></RoleGuard>} />
                        <Route path="ticket-templates" element={<RoleGuard allowedRoles={['admin', 'editor']}><TicketTemplatesPage /></RoleGuard>} />
                        <Route path="recurring-ticket-rules" element={<RoleGuard allowedRoles={['admin', 'editor']}><RecurringTicketsPage /></RoleGuard>} />
                        <Route path="insurance-certificates" element={<RoleGuard allowedRoles={['admin', 'editor']}><InsuranceCertificatesPage /></RoleGuard>} />
                        <Route path="space" element={<SpacePage />} />
                        {/* Backwards-compatible redirects from the pre-consolidation URLs */}
                        <Route path="financial-dashboard" element={<Navigate to="/dashboard/financial" replace />} />
                        <Route path="analytics" element={<Navigate to="/dashboard/analytics" replace />} />
                        <Route path="reports" element={<Navigate to="/dashboard/reports" replace />} />
                        <Route path="sla-dashboard" element={<Navigate to="/dashboard/sla" replace />} />
                        <Route path="rent-roll" element={<Navigate to="/finance" replace />} />
                        <Route path="leases/rent-roll" element={<Navigate to="/finance" replace />} />
                        <Route path="operating-expenses" element={<Navigate to="/finance/operating-expenses" replace />} />
                        <Route path="general-ledger" element={<Navigate to="/finance/general-ledger" replace />} />
                        <Route path="hq-hvac" element={<Navigate to="/hvac" replace />} />
                        <Route path="hvac-contracts" element={<Navigate to="/hvac/contracts" replace />} />
                        <Route path="*" element={<NotFoundPage />} />
                      </Routes>
                    </Suspense>
                  </AppNavigation>
                </ProtectedRoute>
              }
            />
          </Routes>
        </Suspense>
        </WSProvider>
        </FlashbarProvider>
        </ThemeProvider>
        </PreferencesProvider>
      </AuthProvider>
      </SiteSettingsProvider>
    </BrowserRouter>
  );
};

export default App;
