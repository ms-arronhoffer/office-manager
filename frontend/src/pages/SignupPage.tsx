import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
import { useAuth } from '@/auth/AuthContext';

const SignupPage: React.FC = () => {
  const navigate = useNavigate();
  const { signup, isAuthenticated } = useAuth();

  const [orgName, setOrgName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (isAuthenticated) {
    navigate('/', { replace: true });
    return null;
  }

  const handleSubmit = async () => {
    if (!orgName.trim() || !displayName.trim() || !email.trim() || !password) {
      setError('All fields are required.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      await signup({ org_name: orgName.trim(), display_name: displayName.trim(), email: email.trim(), password });
      navigate('/onboarding', { replace: true });
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Something went wrong. Please try again.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          background: 'linear-gradient(135deg, #0972d3 0%, #033160 100%)',
          padding: '64px 24px',
          textAlign: 'center',
        }}
      >
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
        <div style={{ fontSize: '1.1rem', color: 'rgba(255, 255, 255, 0.85)', maxWidth: '480px', margin: '0 auto' }}>
          Set up your organization in under 2 minutes
        </div>
      </div>

      <Box padding={{ top: 'xxxl', horizontal: 'xxl' }} display="block">
        <Box display="block" margin={{ horizontal: 'auto' }} padding={{ horizontal: 'xxxl' }}>
          <Container
            header={
              <Header variant="h2" description="Create your organization and admin account.">
                Get started for free
              </Header>
            }
          >
            <Form
              actions={
                <SpaceBetween direction="vertical" size="s">
                  <Button
                    variant="primary"
                    loading={isLoading}
                    onClick={handleSubmit}
                    fullWidth
                    formAction="submit"
                  >
                    Create account
                  </Button>
                  <Box textAlign="center">
                    <Link onFollow={() => navigate('/login')}>Already have an account? Sign in</Link>
                  </Box>
                </SpaceBetween>
              }
            >
              <SpaceBetween direction="vertical" size="l">
                {error && (
                  <Alert type="error" dismissible onDismiss={() => setError(null)}>
                    {error}
                  </Alert>
                )}
                <FormField
                  label="Organization name"
                  constraintText="This will be your company or team name."
                >
                  <Input
                    value={orgName}
                    onChange={({ detail }) => setOrgName(detail.value)}
                    placeholder="Acme Corp"
                    disabled={isLoading}
                  />
                </FormField>
                <FormField label="Your full name">
                  <Input
                    value={displayName}
                    onChange={({ detail }) => setDisplayName(detail.value)}
                    placeholder="Jane Smith"
                    disabled={isLoading}
                  />
                </FormField>
                <FormField label="Work email">
                  <Input
                    type="email"
                    value={email}
                    onChange={({ detail }) => setEmail(detail.value)}
                    placeholder="you@company.com"
                    disabled={isLoading}
                  />
                </FormField>
                <FormField label="Password" constraintText="Minimum 8 characters.">
                  <Input
                    type="password"
                    value={password}
                    onChange={({ detail }) => setPassword(detail.value)}
                    placeholder="Choose a password"
                    disabled={isLoading}
                  />
                </FormField>
                <FormField label="Confirm password">
                  <Input
                    type="password"
                    value={confirmPassword}
                    onChange={({ detail }) => setConfirmPassword(detail.value)}
                    placeholder="Repeat your password"
                    disabled={isLoading}
                    onKeyDown={({ detail }) => {
                      if (detail.key === 'Enter') handleSubmit();
                    }}
                  />
                </FormField>
              </SpaceBetween>
            </Form>
          </Container>
        </Box>
      </Box>
    </div>
  );
};

export default SignupPage;
