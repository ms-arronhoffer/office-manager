import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Spinner from '@cloudscape-design/components/spinner';
import Box from '@cloudscape-design/components/box';
import { AuthProvider } from '@/auth/AuthContext';
import { PreferencesProvider } from '@/context/PreferencesContext';
import { FlashbarProvider } from '@/context/FlashbarContext';
import { UnsavedChangesProvider } from '@/context/UnsavedChangesContext';
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
const LegalPage = lazy(() => import('@/pages/LegalPage'));
const OnboardingPage = lazy(() => import('@/pages/OnboardingPage'));
const BillingPage = lazy(() => import('@/pages/BillingPage'));
const ApiKeysPage = lazy(() => import('@/pages/ApiKeysPage'));
const SsoSettingsPage = lazy(() => import('@/pages/SsoSettingsPage'));
const ConnectorsPage = lazy(() => import('@/pages/ConnectorsPage'));
const WebhooksPage = lazy(() => import('@/pages/WebhooksPage'));
const BuildiumConnectorPage = lazy(() => import('@/pages/BuildiumConnectorPage'));
const OfficesPage = lazy(() => import('@/pages/OfficesPage'));
const OfficeDetailPage = lazy(() => import('@/pages/OfficeDetailPage'));
const OfficeFormPage = lazy(() => import('@/pages/OfficeFormPage'));
const OfficeWizardPage = lazy(() => import('@/pages/OfficeWizardPage'));
const LeasesPage = lazy(() => import('@/pages/LeasesPage'));
const LeaseDetailPage = lazy(() => import('@/pages/LeaseDetailPage'));
const LeaseFormPage = lazy(() => import('@/pages/LeaseFormPage'));
const LeaseWizardPage = lazy(() => import('@/pages/LeaseWizardPage'));
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
const InspectionsPage = lazy(() => import('@/pages/InspectionsPage'));
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
const HelpPage = lazy(() => import('@/pages/HelpPage'));
const EmailRulesPage = lazy(() => import('@/pages/EmailRulesPage'));
const EmailCustomizationPage = lazy(() => import('@/pages/EmailCustomizationPage'));
const ProcurementPage = lazy(() => import('@/pages/ProcurementPage'));
const WaiversPage = lazy(() => import('@/pages/WaiversPage'));
const WaiverSignPage = lazy(() => import('@/pages/WaiverSignPage'));
const LeaseSignPage = lazy(() => import('@/pages/LeaseSignPage'));
const ApplicationPage = lazy(() => import('@/pages/ApplicationPage'));
const FinancialVerificationPage = lazy(() => import('@/pages/FinancialVerificationPage'));
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
const ResidentPortalPage = lazy(() => import('@/pages/ResidentPortalPage'));
const OwnerPortalPage = lazy(() => import('@/pages/OwnerPortalPage'));
const InsuranceCertificatesPage = lazy(() => import('@/pages/InsuranceCertificatesPage'));
const SpacePage = lazy(() => import('@/pages/SpacePage'));
const DashboardHubPage = lazy(() => import('@/pages/DashboardHubPage'));
const WorkQueuePage = lazy(() => import('@/pages/WorkQueuePage'));
const FinancePage = lazy(() => import('@/pages/FinancePage'));
const ResidentialPage = lazy(() => import('@/pages/ResidentialPage'));
const ResidentDetailPage = lazy(() => import('@/pages/ResidentDetailPage'));
const UnitDetailPage = lazy(() => import('@/pages/UnitDetailPage'));
const SelfStoragePage = lazy(() => import('@/pages/SelfStoragePage'));
const CategorySettingsPage = lazy(() => import('@/pages/CategorySettingsPage'));
const HvacPage = lazy(() => import('@/pages/HvacPage'));
const MaintenancePage = lazy(() => import('@/pages/MaintenancePage'));
const AssetDetailPage = lazy(() => import('@/pages/AssetDetailPage'));
const AdministrationPage = lazy(() => import('@/pages/AdministrationPage'));
const PlatformAdminPage = lazy(() => import('@/pages/PlatformAdminPage'));
const VerifyEmailPage = lazy(() => import('@/pages/VerifyEmailPage'));

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
        <UnsavedChangesProvider>
        <WSProvider>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/reset-password/:token" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/legal" element={<LegalPage />} />
            <Route path="/legal/:slug" element={<LegalPage />} />
            <Route path="/verify-email/:token" element={<VerifyEmailPage />} />
            <Route path="/vendor-portal" element={<VendorPortalPage />} />
            <Route path="/client-portal" element={<ClientPortalPage />} />
            <Route path="/client-portal/signup" element={<ClientPortalPage />} />
            <Route path="/resident-portal" element={<ResidentPortalPage />} />
            <Route path="/resident-portal/signup" element={<ResidentPortalPage />} />
            <Route path="/owner-portal" element={<OwnerPortalPage />} />
            <Route path="/owner-portal/signup" element={<OwnerPortalPage />} />
            <Route path="/sign/:token" element={<WaiverSignPage />} />
            <Route path="/sign" element={<WaiverSignPage />} />
            <Route path="/lease-sign/:token" element={<LeaseSignPage />} />
            <Route path="/apply/:token" element={<ApplicationPage />} />
            <Route path="/financial-verify/:token" element={<FinancialVerificationPage />} />
            <Route path="/financial-verify" element={<FinancialVerificationPage />} />
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
                        <Route path="my-work" element={<WorkQueuePage />} />
                        <Route path="dashboard/financial" element={<DashboardHubPage />} />
                        <Route path="dashboard/analytics" element={<DashboardHubPage />} />
                        <Route path="dashboard/reports" element={<DashboardHubPage />} />
                        <Route path="dashboard/sla" element={<DashboardHubPage />} />
                        <Route path="offices" element={<OfficesPage />} />
                        <Route path="offices/new" element={<Navigate to="/offices/wizard" replace />} />
                        <Route path="offices/wizard" element={<RoleGuard allowedRoles={['admin', 'editor']}><OfficeWizardPage /></RoleGuard>} />
                        <Route path="offices/:id" element={<OfficeDetailPage />} />
                        <Route path="offices/:id/edit" element={<RoleGuard allowedRoles={['admin', 'editor']}><OfficeFormPage /></RoleGuard>} />
                        <Route path="leases" element={<LeasesPage />} />
                        <Route path="leases/calendar" element={<LeaseCalendarPage />} />
                        <Route path="finance" element={<FinancePage />} />
                        <Route path="finance/operating-expenses" element={<RoleGuard allowedRoles={['admin', 'editor']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/general-ledger" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/financial-statements" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/cam" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/accounts-payable" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/procurement" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/accounts-receivable" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/bank-reconciliation" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/tax-1099" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/budgeting" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="finance/lease-lifecycle" element={<RoleGuard allowedRoles={['admin', 'accountant']}><FinancePage /></RoleGuard>} />
                        <Route path="residential" element={<ResidentialPage />} />
                        <Route path="residential/residents" element={<ResidentialPage />} />
                        <Route path="residential/residents/:id" element={<ResidentDetailPage />} />
                        <Route path="residential/units/:id" element={<UnitDetailPage />} />
                        <Route path="residential/leases" element={<ResidentialPage />} />
                        <Route path="residential/templates" element={<ResidentialPage />} />
                        <Route path="residential/application-templates" element={<ResidentialPage />} />
                        <Route path="residential/applications" element={<ResidentialPage />} />
                        <Route path="residential/listings" element={<ResidentialPage />} />
                        <Route path="residential/announcements" element={<ResidentialPage />} />
                        <Route path="residential/rent" element={<RoleGuard allowedRoles={['admin', 'accountant']}><ResidentialPage /></RoleGuard>} />
                        <Route path="residential/owners" element={<RoleGuard allowedRoles={['admin', 'accountant']}><ResidentialPage /></RoleGuard>} />
                        <Route path="self-storage" element={<SelfStoragePage />} />
                        <Route path="self-storage/properties" element={<SelfStoragePage />} />
                        <Route path="self-storage/units" element={<SelfStoragePage />} />
                        <Route path="self-storage/agreements" element={<SelfStoragePage />} />
                        <Route path="self-storage/reservations" element={<SelfStoragePage />} />
                        <Route path="self-storage/rate-plans" element={<SelfStoragePage />} />
                        <Route path="leases/new" element={<Navigate to="/leases/wizard" replace />} />
                        <Route path="leases/wizard" element={<RoleGuard allowedRoles={['admin', 'editor']}><LeaseWizardPage /></RoleGuard>} />
                        <Route path="leases/:id" element={<LeaseDetailPage />} />
                        <Route path="leases/:id/edit" element={<RoleGuard allowedRoles={['admin', 'editor']}><LeaseFormPage /></RoleGuard>} />
                        <Route path="landlords" element={<LandlordsPage />} />
                        <Route path="landlords/new" element={<RoleGuard allowedRoles={['admin', 'editor']}><LandlordFormPage /></RoleGuard>} />
                        <Route path="landlords/:id" element={<LandlordDetailPage />} />
                        <Route path="landlords/:id/edit" element={<RoleGuard allowedRoles={['admin', 'editor']}><LandlordFormPage /></RoleGuard>} />
                        <Route path="vendors" element={<VendorsPage />} />
                        <Route path="vendors/new" element={<RoleGuard allowedRoles={['admin', 'editor']}><VendorFormPage /></RoleGuard>} />
                        <Route path="vendors/:id" element={<VendorDetailPage />} />
                        <Route path="vendors/:id/edit" element={<RoleGuard allowedRoles={['admin', 'editor']}><VendorFormPage /></RoleGuard>} />
                        <Route path="management-companies" element={<ManagementCompaniesPage />} />
                        <Route path="management-companies/new" element={<RoleGuard allowedRoles={['admin', 'editor']}><ManagementCompanyFormPage /></RoleGuard>} />
                        <Route path="management-companies/:id" element={<ManagementCompanyDetailPage />} />
                        <Route
                          path="management-companies/:id/edit"
                          element={<RoleGuard allowedRoles={['admin', 'editor']}><ManagementCompanyFormPage /></RoleGuard>}
                        />
                        <Route path="transitions" element={<TransitionsPage />} />
                        <Route path="transitions/new" element={<RoleGuard allowedRoles={['admin', 'editor']}><TransitionFormPage /></RoleGuard>} />
                        <Route path="transitions/:id" element={<TransitionDetailPage />} />
                        <Route path="transitions/:id/edit" element={<RoleGuard allowedRoles={['admin', 'editor']}><TransitionFormPage /></RoleGuard>} />
                        <Route path="hvac" element={<HvacPage />} />
                        <Route path="hvac/contracts" element={<HvacPage />} />
                        <Route path="maintenance" element={<MaintenancePage />} />
                        <Route path="maintenance/assets/:id" element={<AssetDetailPage />} />
                        <Route path="maintenance/:category" element={<MaintenancePage />} />
                        <Route path="hvac-contracts/new" element={<RoleGuard allowedRoles={['admin', 'editor']}><HvacContractFormPage /></RoleGuard>} />
                        <Route path="hvac-contracts/:id" element={<HvacContractDetailPage />} />
                        <Route path="hvac-contracts/:id/edit" element={<RoleGuard allowedRoles={['admin', 'editor']}><HvacContractFormPage /></RoleGuard>} />
                        <Route path="administration" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
                        <Route path="administration/automation" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
                        <Route path="administration/integrations" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
                        <Route path="administration/system" element={<RoleGuard allowedRoles={['admin', 'editor']}><AdministrationPage /></RoleGuard>} />
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
                        <Route path="maintenance-tickets/new" element={<RoleGuard allowedRoles={['admin', 'editor']}><MaintenanceTicketFormPage /></RoleGuard>} />
                        <Route path="maintenance-tickets/:id" element={<MaintenanceTicketDetailPage />} />
                        <Route path="maintenance-tickets/:id/edit" element={<RoleGuard allowedRoles={['admin', 'editor']}><MaintenanceTicketFormPage /></RoleGuard>} />
                        <Route path="inspections" element={<InspectionsPage />} />
                        <Route path="users" element={<RoleGuard allowedRoles={['admin']}><UsersPage /></RoleGuard>} />
                        <Route path="data-dictionary" element={<RoleGuard allowedRoles={['admin']}><DataDictionaryPage /></RoleGuard>} />
                        <Route path="email-rules" element={<RoleGuard allowedRoles={['admin']}><EmailRulesPage /></RoleGuard>} />
                        <Route path="email-customization" element={<RoleGuard allowedRoles={['admin']}><EmailCustomizationPage /></RoleGuard>} />
                        <Route path="waivers" element={<RoleGuard allowedRoles={['admin', 'editor']}><WaiversPage /></RoleGuard>} />
                        <Route path="settings" element={<SettingsPage />} />
                        <Route path="help" element={<HelpPage />} />
                        <Route path="activity-log" element={<RoleGuard allowedRoles={['admin']}><ActivityLogPage /></RoleGuard>} />
                        <Route path="trash" element={<RoleGuard allowedRoles={['admin']}><TrashPage /></RoleGuard>} />
                        <Route path="admin/site-settings" element={<RoleGuard allowedRoles={['admin']}><SiteSettingsPage /></RoleGuard>} />
                        <Route path="admin/categories" element={<RoleGuard allowedRoles={['admin']}><CategorySettingsPage /></RoleGuard>} />
                        <Route path="support-requests" element={<RoleGuard allowedRoles={['admin']}><SupportRequestsPage /></RoleGuard>} />
                        <Route path="billing" element={<RoleGuard allowedRoles={['admin']}><BillingPage /></RoleGuard>} />
                        <Route path="api-keys" element={<RoleGuard allowedRoles={['admin']}><ApiKeysPage /></RoleGuard>} />
                        <Route path="admin/sso" element={<RoleGuard allowedRoles={['admin']}><SsoSettingsPage /></RoleGuard>} />
                        <Route path="finance/connections" element={<RoleGuard allowedRoles={['admin', 'accountant']}><ConnectorsPage /></RoleGuard>} />
                        <Route path="webhooks" element={<RoleGuard allowedRoles={['admin']}><WebhooksPage /></RoleGuard>} />
                        <Route path="buildium" element={<RoleGuard allowedRoles={['admin']}><BuildiumConnectorPage /></RoleGuard>} />
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
        </UnsavedChangesProvider>
        </FlashbarProvider>
        </ThemeProvider>
        </PreferencesProvider>
      </AuthProvider>
      </SiteSettingsProvider>
    </BrowserRouter>
  );
};

export default App;
