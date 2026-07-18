import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation, useParams } from 'react-router-dom';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Link from '@cloudscape-design/components/link';
import Toggle from '@cloudscape-design/components/toggle';
import Icon from '@cloudscape-design/components/icon';
import { useAuth } from '@/auth/AuthContext';
import { useSiteSettings } from '@/context/SiteSettingsContext';
import { auth as authApi } from '@/api';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

type Mode = 'login' | 'forgot' | 'reset' | 'mfa';

/**
 * Build a user-facing error message from a request failure.
 *
 * Server outages (e.g. a 502 Bad Gateway from the reverse proxy when the API is
 * down) and network failures must not be reported as "Invalid credentials" — that
 * sends users chasing a password problem that does not exist. Only fall back to
 * the credential-specific message for genuine client errors (4xx) that carry no
 * explanatory detail.
 */
const getRequestErrorMessage = (err: unknown, fallback: string): string => {
  const response = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
  if (!response) {
    return 'Unable to reach the server. Please check your connection and try again.';
  }
  const detail = response.data?.detail;
  if (typeof detail === 'string' && detail) {
    return detail;
  }
  if (typeof response.status === 'number' && response.status >= 500) {
    return 'The server is temporarily unavailable. Please try again in a few moments.';
  }
  return fallback;
};

const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { token: routeResetToken } = useParams<{ token?: string }>();
  const { loginWithToken, googleLogin, isAuthenticated } = useAuth();
  const { settings, reload: reloadSiteSettings } = useSiteSettings();

  const [mode, setMode] = useState<Mode>('login');

  // Login state
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Forgot password state
  const [forgotEmail, setForgotEmail] = useState('');

  // Reset password state
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  // MFA state
  const [mfaToken, setMfaToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [useBackupCode, setUseBackupCode] = useState(false);

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/';

  // Redirect away from the login page once the user is authenticated.
  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, from, navigate]);

  useEffect(() => {
    if (routeResetToken) {
      setMode('reset');
      setResetToken(routeResetToken);
      setError(null);
      setSuccessMessage(null);
    }
  }, [routeResetToken]);

  if (isAuthenticated) {
    return null;
  }

  const switchMode = (next: Mode) => {
    setError(null);
    setSuccessMessage(null);
    setMode(next);
  };

  // ── Login ──────────────────────────────────────────────────────────────────
  const handleLogin = async () => {
    if (!email || !password) {
      setError('Please enter your email and password.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await authApi.login(email, password);
      const data = response.data;
      if (data.mfa_required && data.mfa_token) {
        setMfaToken(data.mfa_token);
        setMfaCode('');
        setUseBackupCode(false);
        setMode('mfa');
      } else if (data.access_token) {
        await loginWithToken(data.access_token);
        // Reload site settings now that user is authenticated
        reloadSiteSettings();
        navigate(from, { replace: true });
      } else {
        setError('Unexpected response. Please try again.');
      }
    } catch (err: unknown) {
      setError(getRequestErrorMessage(err, 'Invalid credentials. Please try again.'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    setError('Google sign-in is not configured. Please use email/password.');
  };

  // ── Forgot Password ────────────────────────────────────────────────────────
  const handleForgotPassword = async () => {
    if (!forgotEmail) {
      setError('Please enter your email address.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      await authApi.forgotPassword(forgotEmail);
      setSuccessMessage(
        'If an account exists for that email, a reset token has been sent. Check your inbox.',
      );
      setMode('reset');
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  // ── Reset Password ─────────────────────────────────────────────────────────
  const handleResetPassword = async () => {
    if (!resetToken || !newPassword) {
      setError('Please enter your reset token and new password.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (newPassword.length < 12) {
      setError('Password must be at least 12 characters.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      await authApi.resetPassword(resetToken, newPassword);
      setSuccessMessage('Your password has been reset. You can now sign in.');
      setMode('login');
      setResetToken('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: unknown) {
      setError(getRequestErrorMessage(err, 'Invalid or expired reset token.'));
    } finally {
      setIsLoading(false);
    }
  };

  // ── MFA Verify ────────────────────────────────────────────────────────────
  const handleMfaVerify = async () => {
    if (!mfaCode) {
      setError('Please enter your authentication code.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await authApi.verifyMfa(mfaToken, mfaCode);
      await loginWithToken(response.data.access_token);
      // Reload site settings now that user is authenticated
      reloadSiteSettings();
      navigate(from, { replace: true });
    } catch (err: unknown) {
      setError(
        getRequestErrorMessage(
          err,
          useBackupCode ? 'Invalid backup code.' : 'Invalid authentication code.',
        ),
      );
    } finally {
      setIsLoading(false);
    }
  };

  // ── Form content per mode ──────────────────────────────────────────────────
  const renderFormHeader = () => {
    if (mode === 'forgot') {
      return (
        <Header variant="h2" description="Enter your email and we'll send you a reset token.">
          Reset Password
        </Header>
      );
    }
    if (mode === 'reset') {
      return (
        <Header variant="h2" description="Enter the token from your email and choose a new password.">
          Set New Password
        </Header>
      );
    }
    if (mode === 'mfa') {
      return (
        <Header
          variant="h2"
          description={
            useBackupCode
              ? 'Enter one of your 12-character backup codes.'
              : 'Enter the 6-digit code from your authenticator app.'
          }
        >
          Two-Factor Authentication
        </Header>
      );
    }
    return (
      <Header variant="h2" description={settings.login_form_description}>
        {settings.login_form_header}
      </Header>
    );
  };

  const renderFormBody = () => {
    if (mode === 'forgot') {
      return (
        <SpaceBetween direction="vertical" size="l">
          {error && (
            <Alert type="error" dismissible onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}
          <FormField label="Email address">
            <Input
              type="email"
              value={forgotEmail}
              onChange={({ detail }) => setForgotEmail(detail.value)}
              placeholder="you@example.com"
              disabled={isLoading}
              onKeyDown={({ detail }) => { if (detail.key === 'Enter') handleForgotPassword(); }}
            />
          </FormField>
        </SpaceBetween>
      );
    }

    if (mode === 'reset') {
      return (
        <SpaceBetween direction="vertical" size="l">
          {error && (
            <Alert type="error" dismissible onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}
          {successMessage && (
            <Alert type="success" dismissible onDismiss={() => setSuccessMessage(null)}>
              {successMessage}
            </Alert>
          )}
          <FormField label="Reset token" description="Paste the token from the email you received.">
            <Input
              value={resetToken}
              onChange={({ detail }) => setResetToken(detail.value)}
              placeholder="Paste reset token here"
              disabled={isLoading}
            />
          </FormField>
          <FormField
            label="New password"
            constraintText="Use at least 12 characters and include 3 of: uppercase, lowercase, number, special character."
          >
            <Input
              type="password"
              value={newPassword}
              onChange={({ detail }) => setNewPassword(detail.value)}
              placeholder="Choose a strong password"
              disabled={isLoading}
            />
          </FormField>
          <FormField label="Confirm new password">
            <Input
              type="password"
              value={confirmPassword}
              onChange={({ detail }) => setConfirmPassword(detail.value)}
              placeholder="Repeat new password"
              disabled={isLoading}
              onKeyDown={({ detail }) => { if (detail.key === 'Enter') handleResetPassword(); }}
            />
          </FormField>
        </SpaceBetween>
      );
    }

    // MFA mode
    if (mode === 'mfa') {
      return (
        <SpaceBetween direction="vertical" size="l">
          {error && (
            <Alert type="error" dismissible onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}
          <FormField label={useBackupCode ? 'Backup code' : 'Authentication code'}>
            <Input
              value={mfaCode}
              onChange={({ detail }) => { setMfaCode(detail.value); setError(null); }}
              placeholder={useBackupCode ? '12-character backup code' : '6-digit code'}
              inputMode={useBackupCode ? 'text' : 'numeric'}
              disabled={isLoading}
              onKeyDown={({ detail }) => { if (detail.key === 'Enter') handleMfaVerify(); }}
              autoFocus
            />
          </FormField>
          <Toggle
            checked={useBackupCode}
            onChange={({ detail }) => { setUseBackupCode(detail.checked); setMfaCode(''); setError(null); }}
          >
            Use a backup code instead
          </Toggle>
        </SpaceBetween>
      );
    }

    // Login mode
    return (
      <SpaceBetween direction="vertical" size="l">
        {error && (
          <Alert type="error" dismissible onDismiss={() => setError(null)}>
            {error}
          </Alert>
        )}
        {successMessage && (
          <Alert type="success" dismissible onDismiss={() => setSuccessMessage(null)}>
            {successMessage}
          </Alert>
        )}
        <FormField label="Email address" constraintText="Enter your work email address">
          <Input
            type="email"
            value={email}
            onChange={({ detail }) => setEmail(detail.value)}
            placeholder="you@example.com"
            disabled={isLoading}
            onKeyDown={({ detail }) => { if (detail.key === 'Enter') handleLogin(); }}
          />
        </FormField>
        <FormField
          label="Password"
          secondaryControl={
            <Link onFollow={() => switchMode('forgot')}>Forgot password?</Link>
          }
        >
          <Input
            type="password"
            value={password}
            onChange={({ detail }) => setPassword(detail.value)}
            placeholder="Enter your password"
            disabled={isLoading}
            onKeyDown={({ detail }) => { if (detail.key === 'Enter') handleLogin(); }}
          />
        </FormField>
      </SpaceBetween>
    );
  };

  const renderFormActions = () => {
    if (mode === 'forgot') {
      return (
        <SpaceBetween direction="vertical" size="s">
          <Button variant="primary" loading={isLoading} onClick={handleForgotPassword} fullWidth>
            Send Reset Token
          </Button>
          <Button variant="link" onClick={() => { switchMode('reset'); }}>
            I already have a token
          </Button>
          <Button variant="link" onClick={() => switchMode('login')}>
            Back to sign in
          </Button>
        </SpaceBetween>
      );
    }

    if (mode === 'reset') {
      return (
        <SpaceBetween direction="vertical" size="s">
          <Button variant="primary" loading={isLoading} onClick={handleResetPassword} fullWidth>
            Reset Password
          </Button>
          <Button variant="link" onClick={() => switchMode('login')}>
            Back to sign in
          </Button>
        </SpaceBetween>
      );
    }

    if (mode === 'mfa') {
      return (
        <SpaceBetween direction="vertical" size="s">
          <Button variant="primary" loading={isLoading} onClick={handleMfaVerify} fullWidth>
            Verify
          </Button>
          <Button variant="link" onClick={() => switchMode('login')}>
            Back to sign in
          </Button>
        </SpaceBetween>
      );
    }

    return (
      <SpaceBetween direction="vertical" size="s">
        <Button
          variant="primary"
          loading={isLoading}
          onClick={handleLogin}
          fullWidth
          formAction="submit"
        >
          Sign In
        </Button>
        {GOOGLE_CLIENT_ID && (
          <Button
            variant="normal"
            loading={isLoading}
            onClick={handleGoogleLogin}
            fullWidth
            iconName="external"
          >
            Sign in with Google
          </Button>
        )}
        <Box textAlign="center">
          <Link onFollow={() => navigate('/signup')}>New here? Create an account</Link>
        </Box>
      </SpaceBetween>
    );
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Hero Banner */}
      <div
        style={{
          position: 'relative',
          overflow: 'hidden',
          background: 'radial-gradient(circle at 15% 20%, #0f6ab0 0%, transparent 45%), ' +
            'radial-gradient(circle at 85% 0%, #1a3f70 0%, transparent 55%), ' +
            'linear-gradient(160deg, #06182f 0%, #0a2b52 45%, #0972d3 100%)',
          padding: '72px 24px 96px',
          textAlign: 'center',
        }}
      >
        {/* Subtle grid overlay for depth */}
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px), ' +
              'linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px)',
            backgroundSize: '40px 40px',
            maskImage: 'radial-gradient(ellipse at center, black 0%, transparent 75%)',
            WebkitMaskImage: 'radial-gradient(ellipse at center, black 0%, transparent 75%)',
          }}
        />

        <div style={{ position: 'relative' }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '56px',
              height: '56px',
              borderRadius: '16px',
              background: 'rgba(255, 255, 255, 0.12)',
              border: '1px solid rgba(255, 255, 255, 0.25)',
              boxShadow: '0 8px 24px rgba(0, 0, 0, 0.25)',
              marginBottom: '20px',
            }}
          >
            <Icon name="security" size="medium" variant="inverted" />
          </div>

          <div
            style={{
              fontSize: '2.5rem',
              fontWeight: 700,
              color: '#ffffff',
              letterSpacing: '-0.5px',
              marginBottom: '12px',
            }}
          >
            Portfolio Desk
          </div>
          <div
            style={{
              fontSize: '1.1rem',
              color: 'rgba(255, 255, 255, 0.85)',
              maxWidth: '480px',
              margin: '0 auto 28px',
            }}
          >
            {settings.login_subtitle}
          </div>

          <div
            style={{
              display: 'inline-flex',
              flexWrap: 'wrap',
              justifyContent: 'center',
              gap: '10px 24px',
              fontSize: '0.85rem',
              color: 'rgba(255, 255, 255, 0.75)',
            }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <Icon name="lock-private" variant="inverted" size="small" /> Encrypted in transit &amp; at rest
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <Icon name="status-positive" variant="inverted" size="small" /> Trusted by growing teams
            </span>
          </div>
        </div>
      </div>

      {/* Login Form */}
      <div style={{ marginTop: '-56px', padding: '0 24px 64px' }}>
        <Box
          display="block"
          margin={{ horizontal: 'auto' }}
          padding={{ horizontal: 'xxxl' }}
        >
          <div style={{ borderRadius: '16px', boxShadow: '0 20px 48px rgba(3, 49, 96, 0.18)' }}>
            <Container header={renderFormHeader()}>
              <Form actions={renderFormActions()}>
                {renderFormBody()}
              </Form>
            </Container>
          </div>
        </Box>
      </div>
    </div>
  );
};

export default LoginPage;
