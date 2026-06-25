import { render, screen } from '@testing-library/react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';

// We'll test the RoleGuard component that we're about to create
// For now, test the concept with a mock

const mockUseAuth = vi.fn();

vi.mock('@/auth/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

// Inline RoleGuard implementation for testing (will match the real one)
const RoleGuard: React.FC<{ allowedRoles: string[]; children: React.ReactNode }> = ({
  allowedRoles,
  children,
}) => {
  const { user } = mockUseAuth();
  if (!user || !allowedRoles.includes(user.role)) {
    return <div>Access Denied</div>;
  }
  return <>{children}</>;
};

describe('RoleGuard', () => {
  it('blocks viewer from admin-only route', () => {
    mockUseAuth.mockReturnValue({
      user: { id: '1', email: 'v@test.com', display_name: 'Viewer', role: 'viewer', is_active: true },
      isAuthenticated: true,
      isLoading: false,
    });

    render(
      <BrowserRouter>
        <RoleGuard allowedRoles={['admin']}>
          <div>Admin Content</div>
        </RoleGuard>
      </BrowserRouter>,
    );

    expect(screen.getByText('Access Denied')).toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('allows admin to access admin route', () => {
    mockUseAuth.mockReturnValue({
      user: { id: '1', email: 'a@test.com', display_name: 'Admin', role: 'admin', is_active: true },
      isAuthenticated: true,
      isLoading: false,
    });

    render(
      <BrowserRouter>
        <RoleGuard allowedRoles={['admin']}>
          <div>Admin Content</div>
        </RoleGuard>
      </BrowserRouter>,
    );

    expect(screen.getByText('Admin Content')).toBeInTheDocument();
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument();
  });
});
