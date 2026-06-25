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

const { default: MaintenanceTicketsPage } = await import('@/pages/MaintenanceTicketsPage');

function renderPage() {
  return render(
    <BrowserRouter>
      <PreferencesProvider>
        <MaintenanceTicketsPage />
      </PreferencesProvider>
    </BrowserRouter>,
  );
}

describe('MaintenanceTicketsPage', () => {
  it('shows loading state initially', () => {
    renderPage();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders tickets after loading', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Broken pipe')).toBeInTheDocument();
    });
  });
});
