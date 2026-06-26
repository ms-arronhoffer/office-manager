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
import { waiverPublic } from '@/api';
import type { PublicWaiverView } from '@/types';

const WaiverSignPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();

  const [waiver, setWaiver] = useState<PublicWaiverView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [signerName, setSignerName] = useState('');
  const [signerEmail, setSignerEmail] = useState('');
  const [signature, setSignature] = useState('');
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState<'signed' | 'declined' | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await waiverPublic.view(token);
      setWaiver(res.data);
      if (res.data.status === 'signed') setDone('signed');
      if (res.data.status === 'declined') setDone('declined');
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(status === 410 ? 'This waiver link has expired.' : 'This waiver could not be found.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    if (!token) return;
    if (!signerName.trim() || !signature.trim()) {
      setError('Please enter your name and signature.');
      return;
    }
    if (!consent) {
      setError('You must consent to sign electronically.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await waiverPublic.sign(token, {
        signer_name: signerName,
        signer_email: signerEmail || null,
        signature_type: 'typed',
        signature_data: signature,
        consent_agreed: true,
      });
      setDone('signed');
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 409
          ? 'This waiver has already been completed.'
          : status === 410
            ? 'This waiver link has expired.'
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
      await waiverPublic.decline(token);
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
        <Header variant="h1" description={waiver?.organization_name || undefined}>
          {waiver?.title || 'Waiver'}
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
              You have declined this waiver. You may close this window.
            </Alert>
          )}

          <Container header={<Header variant="h2">Document</Header>}>
            <Box variant="p">
              <span style={{ whiteSpace: 'pre-wrap' }}>{waiver?.body}</span>
            </Box>
          </Container>

          {!done && (
            <Container header={<Header variant="h2">Sign electronically</Header>}>
              <SpaceBetween size="m">
                <FormField label="Full name">
                  <Input value={signerName} onChange={(e) => setSignerName(e.detail.value)} />
                </FormField>
                <FormField label="Email" description="Optional, for your records.">
                  <Input
                    type="email"
                    value={signerEmail}
                    onChange={(e) => setSignerEmail(e.detail.value)}
                  />
                </FormField>
                <FormField
                  label="Signature"
                  description="Type your full legal name to sign."
                >
                  <Input value={signature} onChange={(e) => setSignature(e.detail.value)} />
                </FormField>
                <Checkbox checked={consent} onChange={(e) => setConsent(e.detail.checked)}>
                  {waiver?.consent_text}
                </Checkbox>
                <SpaceBetween direction="horizontal" size="xs">
                  <Button variant="primary" onClick={submit} loading={submitting} disabled={!consent}>
                    Sign waiver
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

export default WaiverSignPage;
