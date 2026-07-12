import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderHook, waitFor as waitForHook } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { FlashbarProvider } from '@/context/FlashbarContext';
import { useCategories } from '@/hooks/useCategories';

// Simulate an authenticated admin user for pages that read useAuth.
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

const { default: CategorySettingsPage } = await import('@/pages/CategorySettingsPage');
const { default: SelfStoragePage } = await import('@/pages/SelfStoragePage');

function renderWithProviders(node: React.ReactNode) {
  return render(
    <BrowserRouter>
      <FlashbarProvider>{node}</FlashbarProvider>
    </BrowserRouter>,
  );
}

describe('useCategories', () => {
  it('resolves the effective category set from the API', async () => {
    const { result } = renderHook(() => useCategories());
    await waitForHook(() => expect(result.current.loading).toBe(false));
    expect(result.current.catalog).toEqual(['commercial', 'residential', 'self_storage']);
    expect(result.current.isEnabled('commercial')).toBe(true);
    expect(result.current.isEnabled('self_storage')).toBe(false);
  });
});

describe('CategorySettingsPage', () => {
  it('renders a toggle per primary category', async () => {
    renderWithProviders(<CategorySettingsPage />);
    await waitFor(() => {
      expect(screen.getByText('Business categories')).toBeInTheDocument();
    });
    expect(screen.getByText('Commercial')).toBeInTheDocument();
    expect(screen.getByText('Residential')).toBeInTheDocument();
    expect(screen.getByText('Self Storage')).toBeInTheDocument();
  });
});

describe('SelfStoragePage', () => {
  it('renders the self storage tabs and overview summary', async () => {
    renderWithProviders(<SelfStoragePage />);
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'Units' })).toBeInTheDocument();
    });
    // Overview tab shows occupancy metrics from the mocked summary endpoint.
    await waitFor(() => {
      expect(screen.getByText('Occupancy & revenue')).toBeInTheDocument();
    });
  });

  it('navigates to the Units tab', async () => {
    const user = userEvent.setup();
    renderWithProviders(<SelfStoragePage />);
    await user.click(await screen.findByRole('tab', { name: 'Units' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add unit/i })).toBeInTheDocument();
    });
  });
});
