import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Checkbox from '@cloudscape-design/components/checkbox';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import { leasingFunnelPublic } from '@/api';
import type { PublicLeaseView } from '@/types';

const LeaseSignPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();

  const [lease, setLease] = useState<PublicLeaseView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [signature, setSignature] = useState('');
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState<'signed' | 'declined' | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await leasingFunnelPublic.view(token);
      setLease(res.data);
      if (res.data.party_status === 'signed') setDone('signed');
      if (res.data.party_status === 'declined' || res.data.request_status === 'declined') {
        setDone('declined');
      }
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 410 ? 'This lease link has expired.' : 'This lease could not be found.',
      );
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    if (!token) return;
    if (!signature.trim()) {
      setError('Please type your full legal name to sign.');
      return;
    }
    if (!consent) {
      setError('You must consent to sign electronically.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await leasingFunnelPublic.sign(token, {
        signature_type: 'typed',
        signature_data: signature,
        consent_agreed: true,
      });
      setLease(res.data);
      setDone('signed');
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 409
          ? 'This lease can no longer be signed.'
          : status === 410
            ? 'This lease link has expired.'
            : 'Failed to submit signature. Please try again.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  const decline = async () => {
    if (!token) return;
    setSubmitting(true);
    try {
      await leasingFunnelPublic.decline(token);
      setDone('declined');
    } catch {
      setError('Failed to decline.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Box textAlign="center" padding={{ top: 'xxxl' }}>
        <Spinner size="large" />
      </Box>
    );
  }

  return (
    <ContentLayout
      header={
        <Header variant="h1" description={lease ? `For ${lease.signer_name}` : undefined}>
          {lease?.title || 'Lease Agreement'}
        </Header>
      }
    >
      <Box padding={{ horizontal: 'l' }}>
        <SpaceBetween size="l">
          {error && <Alert type="error">{error}</Alert>}

          {done === 'signed' && (
            <Alert type="success" header="Thank you">
              Your signature has been recorded. You may close this window.
            </Alert>
          )}
          {done === 'declined' && (
            <Alert type="info" header="Declined">
              You have declined this lease. You may close this window.
            </Alert>
          )}

          <Container header={<Header variant="h2">Lease document</Header>}>
            <Box variant="p">
              <span style={{ whiteSpace: 'pre-wrap' }}>{lease?.body}</span>
            </Box>
          </Container>

          {!done && (
            <Container header={<Header variant="h2">Sign electronically</Header>}>
              <SpaceBetween size="m">
                <FormField label="Signature" description="Type your full legal name to sign.">
                  <Input value={signature} onChange={(e) => setSignature(e.detail.value)} />
                </FormField>
                <Checkbox checked={consent} onChange={(e) => setConsent(e.detail.checked)}>
                  {lease?.consent_text}
                </Checkbox>
                <SpaceBetween direction="horizontal" size="xs">
                  <Button
                    variant="primary"
                    onClick={submit}
                    loading={submitting}
                    disabled={!consent}
                  >
                    Sign lease
                  </Button>
                  <Button onClick={decline} disabled={submitting}>
                    Decline
                  </Button>
                </SpaceBetween>
              </SpaceBetween>
            </Container>
          )}
        </SpaceBetween>
      </Box>
    </ContentLayout>
  );
};

export default LeaseSignPage;
