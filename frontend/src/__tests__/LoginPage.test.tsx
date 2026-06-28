import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import LoginPage from '@/pages/LoginPage';
import { AuthProvider } from '@/auth/AuthContext';
import { auth as authApi } from '@/api';

function renderLoginPage() {
  return render(
    <BrowserRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </BrowserRouter>,
  );
}

describe('LoginPage', () => {
  it('renders sign-in form with email and password fields', () => {
    renderLoginPage();
    expect(screen.getByPlaceholderText('you@example.com')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Enter your password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows error when submitting empty form', async () => {
    renderLoginPage();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText(/please enter your email and password/i)).toBeInTheDocument();
  });

  it('reports a server error instead of invalid credentials on a 502', async () => {
    const spy = vi
      .spyOn(authApi, 'login')
      .mockRejectedValueOnce({ response: { status: 502, data: {} } });
    renderLoginPage();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('you@example.com'), 'admin@officemanager.local');
    await user.type(screen.getByPlaceholderText('Enter your password'), 'password123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText(/server is temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/invalid credentials/i)).not.toBeInTheDocument();
    spy.mockRestore();
  });

  it('shows the credential error on a 401 with no detail', async () => {
    const spy = vi
      .spyOn(authApi, 'login')
      .mockRejectedValueOnce({ response: { status: 401, data: {} } });
    renderLoginPage();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('you@example.com'), 'admin@officemanager.local');
    await user.type(screen.getByPlaceholderText('Enter your password'), 'wrongpass');
    await user.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText(/invalid credentials/i)).toBeInTheDocument();
    spy.mockRestore();
  });
});
