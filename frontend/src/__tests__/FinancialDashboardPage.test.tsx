import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { PreferencesProvider } from '@/context/PreferencesContext';

vi.mock('@/auth/AuthContext', async () => {
  const actual = await vi.importActual<typeof import('@/auth/AuthContext')>('@/auth/AuthContext');
  return {
    ...actual,
    useAuth: () => ({
      user: {
        id: '00000000-0000-0000-0000-000000000001',
        email: 'admin@test.com',
        display_name: 'Test Admin',
        auth_provider: 'internal',
        role: 'admin',
        is_active: true,
        last_login_at: null,
        created_at: '2024-01-01T00:00:00Z',
      },
      token: 'test-token',
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      googleLogin: vi.fn(),
      logout: vi.fn(),
    }),
  };
});

const { default: FinancialDashboardPage } = await import('@/pages/FinancialDashboardPage');

function renderPage() {
  return render(
    <BrowserRouter>
      <PreferencesProvider>
        <FinancialDashboardPage />
      </PreferencesProvider>
    </BrowserRouter>,
  );
}

describe('FinancialDashboardPage', () => {
  it('renders composed financial KPIs from existing endpoints', async () => {
    renderPage();

    // Total annual rent obligation from rent-roll mock (120000)
    await waitFor(() => {
      expect(screen.getByText('Total Annual Rent Obligation')).toBeInTheDocument();
    });
    expect(screen.getByText('$120,000')).toBeInTheDocument();

    // ROU asset from portfolio mock (450000) — appears in the KPI tile and the summary
    expect(screen.getByText('Total ROU Asset')).toBeInTheDocument();
    expect(screen.getAllByText('$450,000').length).toBeGreaterThan(0);

    // CAM over budget — one category over budget in the mock
    expect(screen.getByText('CAM Categories Over Budget')).toBeInTheDocument();

    // Lease accounting and expiration risk sections render
    expect(screen.getByText('Lease Accounting (ASC 842 / IFRS 16)')).toBeInTheDocument();
    expect(screen.getByText('Lease Expiration Risk')).toBeInTheDocument();
  });
});
