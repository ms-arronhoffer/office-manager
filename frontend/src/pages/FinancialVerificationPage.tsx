import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import Alert from '@cloudscape-design/components/alert';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Checkbox from '@cloudscape-design/components/checkbox';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import { financialVerificationPublic } from '@/api';
import { openPlaidLink } from '@/lib/plaidLink';
import type { PublicFinancialVerification } from '@/types';

type PageState = 'loading' | 'disclosure' | 'linking' | 'processing' | 'completed' | 'action_required' | 'error' | 'declined' | 'expired' | 'revoked';

const FinancialVerificationPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const [view, setView] = useState<PublicFinancialVerification | null>(null);
  const [pageState, setPageState] = useState<PageState>('loading');
  const [accepted, setAccepted] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    void (async () => {
      try {
        if (token) {
          await financialVerificationPublic.exchangeSession(token);
          window.history.replaceState(null, '', '/financial-verify');
        }
        const response = await financialVerificationPublic.view();
        setView(response.data);
        const terminal = ['completed', 'action_required', 'error', 'declined', 'expired', 'revoked'];
        setPageState(terminal.includes(response.data.status) ? response.data.status as PageState : 'disclosure');
      } catch {
        setPageState('error');
        setMessage('This financial verification link is invalid or no longer active.');
      }
    })();
  }, [token]);

  const continueToPlaid = async () => {
    if (!accepted) return;
    setPageState('linking');
    try {
      const consent = await financialVerificationPublic.consent();
      const result = await openPlaidLink(consent.data.link_token);
      if (!result) {
        setPageState('disclosure');
        return;
      }
      setPageState('processing');
      const exchange = await financialVerificationPublic.exchange(
        result.publicToken,
        result.metadata.institution?.name,
      );
      setMessage(exchange.data.message);
      setPageState(exchange.data.status === 'completed' ? 'completed' : 'processing');
    } catch {
      setPageState('error');
      setMessage('The secure bank verification could not be completed. Contact the requesting organization for assistance.');
    }
  };

  const decline = async () => {
    await financialVerificationPublic.decline();
    setPageState('declined');
  };

  if (pageState === 'loading') {
    return <Box textAlign="center" padding="xxxl"><Spinner size="large" /></Box>;
  }

  if (pageState !== 'disclosure' && pageState !== 'linking') {
    const success = pageState === 'completed';
    return (
      <Box margin={{ vertical: 'xxxl', horizontal: 'l' }}>
        <Container header={<Header>{success ? 'Financial verification complete' : 'Financial verification status'}</Header>}>
          <Alert type={success ? 'success' : pageState === 'processing' ? 'info' : 'warning'}>
            {message || (success
              ? 'Your financial verification is complete. You may close this page.'
              : pageState === 'processing'
                ? 'Your information is being processed.'
                : `This request is ${pageState.replace('_', ' ')}. Contact the requesting organization if you need help.`)}
          </Alert>
        </Container>
      </Box>
    );
  }

  if (!view) return null;
  return (
    <Box margin={{ vertical: 'xxxl', horizontal: 'l' }}>
      <Container
        header={<Header variant="h1">Financial verification for {view.applicant_first_name}</Header>}
        footer={
          <SpaceBetween direction="horizontal" size="s">
            <Button variant="link" onClick={decline}>Decline</Button>
            <Button variant="primary" disabled={!accepted} loading={pageState === 'linking'} onClick={continueToPlaid}>
              Continue to secure bank connection
            </Button>
          </SpaceBetween>
        }
      >
        <SpaceBetween size="l">
          <Alert type="info">
            {view.organization_name} requested this verification for your rental application
            {view.property_unit_label ? ` for ${view.property_unit_label}` : ''}.
          </Alert>
          <div>
            <Box variant="h2">Checks requested</Box>
            <ul>{view.requested_checks.map((check) => <li key={check}>{check}</li>)}</ul>
          </div>
          <div>
            <Box variant="h2">Your data and consent</Box>
            <Box>{view.disclosure_text}</Box>
          </div>
          <Alert type="warning">
            Plaid receives your bank login within its secure connection. Portfolio Desk and {view.organization_name} do not receive your credentials. Account and routing numbers, raw identity details, and transaction rows are not retained.
          </Alert>
          <Checkbox checked={accepted} onChange={({ detail }) => setAccepted(detail.checked)}>
            I have read the disclosure and explicitly consent to the requested financial verification.
          </Checkbox>
          <Box color="text-body-secondary">Request expires {new Date(view.expires_at).toLocaleString()}.</Box>
        </SpaceBetween>
      </Container>
    </Box>
  );
};

export default FinancialVerificationPage;