import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { auth } from '@/api';

const VerifyEmailPage: React.FC = () => {
  const navigate = useNavigate();
  const { token = '' } = useParams<{ token: string }>();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('Verifying your email…');

  useEffect(() => {
    let active = true;
    const verify = async () => {
      try {
        await auth.verifyEmail(token);
        if (!active) return;
        setStatus('success');
        setMessage('Your email has been verified. You can continue in the app or sign in again at any time.');
      } catch (err: unknown) {
        if (!active) return;
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          'This verification link is invalid or has expired.';
        setStatus('error');
        setMessage(detail);
      }
    };
    if (!token) {
      setStatus('error');
      setMessage('Missing verification token.');
      return () => {
        active = false;
      };
    }
    void verify();
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <Box padding={{ top: 'xxxl', horizontal: 'xxl' }}>
      <Container
        header={
          <Header variant="h2">
            Verify email
          </Header>
        }
      >
        <SpaceBetween direction="vertical" size="l">
          <Alert type={status === 'success' ? 'success' : status === 'error' ? 'error' : 'info'}>
            {message}
          </Alert>
          <Button onClick={() => navigate('/login')} variant="primary">
            Go to sign in
          </Button>
          <Link to="/signup">Create another account</Link>
        </SpaceBetween>
      </Container>
    </Box>
  );
};

export default VerifyEmailPage;
