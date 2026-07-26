import React, { useEffect, useState } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Button from '@cloudscape-design/components/button';
import Checkbox from '@cloudscape-design/components/checkbox';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Link from '@cloudscape-design/components/link';
import { auth, legal } from '@/api';
import { useAuth } from '@/auth/AuthContext';
import type { LegalDocumentMeta } from '@/types';

/**
 * Renders the "I agree to …" label with inline links to each required legal
 * document (opened in a new tab so the acceptance screen is preserved).
 */
const LegalAgreementLabel: React.FC<{ docs: LegalDocumentMeta[] }> = ({ docs }) => {
  if (docs.length === 0) {
    return (
      <span>
        I have read and agree to the{' '}
        <Link href="/legal" external>
          Terms of Service, EULA, Privacy Policy, and Acceptable Use Policy
        </Link>
        .
      </span>
    );
  }
  return (
    <span>
      I have read and agree to the{' '}
      {docs.map((doc, index) => (
        <React.Fragment key={doc.slug}>
          {index > 0 && (index === docs.length - 1 ? ', and ' : ', ')}
          <Link href={`/legal/${doc.slug}`} external>
            {doc.title}
          </Link>
        </React.Fragment>
      ))}
      .
    </span>
  );
};

/**
 * Blocking screen shown on first login when a user has not yet accepted the
 * required legal documents. The user's account is only treated as active once
 * they agree; acceptance is recorded on the server for auditing.
 */
const LegalGate: React.FC = () => {
  const { refreshUser, logout } = useAuth();
  const [accepted, setAccepted] = useState(false);
  const [legalDocs, setLegalDocs] = useState<LegalDocumentMeta[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    legal
      .list()
      .then((res) => setLegalDocs(res.data.filter((doc) => doc.required_at_signup)))
      .catch(() => setLegalDocs([]));
  }, []);

  const handleAccept = async () => {
    if (!accepted) {
      setError('You must accept the legal documents to continue.');
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await auth.acceptLegal();
      await refreshUser();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Something went wrong. Please try again.';
      setError(message);
      setIsSubmitting(false);
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
        <div
          style={{
            fontSize: '1.1rem',
            color: 'rgba(255, 255, 255, 0.85)',
            maxWidth: '480px',
            margin: '0 auto',
          }}
        >
          Review and accept our legal terms to activate your account
        </div>
      </div>

      <Box padding={{ top: 'xxxl', horizontal: 'xxl' }} display="block">
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <Container
            header={
              <Header
                variant="h2"
                description="Before you can use Portfolio Desk, please review and accept the documents below."
              >
                Accept the terms to continue
              </Header>
            }
          >
            <Form
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  <Button variant="link" onClick={logout} disabled={isSubmitting}>
                    Sign out
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleAccept}
                    loading={isSubmitting}
                    disabled={!accepted}
                  >
                    Agree and continue
                  </Button>
                </SpaceBetween>
              }
            >
              <SpaceBetween direction="vertical" size="l">
                {error && (
                  <Alert type="error" dismissible onDismiss={() => setError(null)}>
                    {error}
                  </Alert>
                )}
                <FormField>
                  <Checkbox
                    checked={accepted}
                    onChange={({ detail }) => setAccepted(detail.checked)}
                  >
                    <LegalAgreementLabel docs={legalDocs} />
                  </Checkbox>
                </FormField>
              </SpaceBetween>
            </Form>
          </Container>
        </div>
      </Box>
    </div>
  );
};

export default LegalGate;
