import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import RoleGuard from '@/auth/RoleGuard';

const mockUseAuth = vi.fn();

vi.mock('@/auth/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

describe('RoleGuard', () => {
  it('redirects viewer from an operational mutation route', () => {
    mockUseAuth.mockReturnValue({
      user: { id: '1', email: 'v@test.com', display_name: 'Viewer', role: 'viewer', is_active: true },
      isAuthenticated: true,
      isLoading: false,
    });

    render(
      <MemoryRouter initialEntries={['/offices/wizard']}>
        <Routes>
          <Route path="/" element={<div>Dashboard</div>} />
          <Route path="/offices/wizard" element={
            <RoleGuard allowedRoles={['admin', 'editor']}>
              <div>Create Office</div>
            </RoleGuard>
          } />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.queryByText('Create Office')).not.toBeInTheDocument();
  });

  it('allows admin to access admin route', () => {
    mockUseAuth.mockReturnValue({
      user: { id: '1', email: 'a@test.com', display_name: 'Admin', role: 'admin', is_active: true },
      isAuthenticated: true,
      isLoading: false,
    });

    render(
      <MemoryRouter>
        <RoleGuard allowedRoles={['admin']}>
          <div>Admin Content</div>
        </RoleGuard>
      </MemoryRouter>,
    );

    expect(screen.getByText('Admin Content')).toBeInTheDocument();
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument();
  });
});
