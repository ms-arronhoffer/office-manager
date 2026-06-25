import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AuthProvider } from '@/auth/AuthContext';
import { PreferencesProvider } from '@/context/PreferencesContext';

// Mock the auth module to simulate an authenticated admin user
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

// Lazy import after mock
const { default: OfficesPage } = await import('@/pages/OfficesPage');

function renderPage() {
  return render(
    <BrowserRouter>
      <PreferencesProvider>
        <OfficesPage />
      </PreferencesProvider>
    </BrowserRouter>,
  );
}

describe('OfficesPage', () => {
  it('shows loading state initially', () => {
    renderPage();
    expect(screen.getByText(/loading offices/i)).toBeInTheDocument();
  });

  it('renders offices table after loading', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Main Office')).toBeInTheDocument();
    });
  });
});
