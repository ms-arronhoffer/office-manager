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
import Textarea from '@cloudscape-design/components/textarea';
import Checkbox from '@cloudscape-design/components/checkbox';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import { leasingFunnelPublic } from '@/api';
import type { PublicApplicationView } from '@/types';

const ApplicationPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();

  const [application, setApplication] = useState<PublicApplicationView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [values, setValues] = useState<Record<string, string>>({});
  const [signature, setSignature] = useState('');
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await leasingFunnelPublic.viewApplication(token);
      setApplication(res.data);
      if (res.data.signed) setDone(true);
      // Seed any previously-saved field values.
      const data = res.data.application_data ?? {};
      const seeded: Record<string, string> = {};
      for (const f of res.data.field_schema ?? []) {
        const v = data[f.key];
        if (v != null) seeded[f.key] = String(v);
      }
      setValues(seeded);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 410
          ? 'This application link has expired.'
          : 'This application could not be found.',
      );
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const setValue = (key: string, value: string) =>
    setValues((prev) => ({ ...prev, [key]: value }));

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
    const missing = (application?.field_schema ?? []).filter(
      (f) => f.required && !(values[f.key] ?? '').trim(),
    );
    if (missing.length > 0) {
      setError(`Please complete: ${missing.map((f) => f.label).join(', ')}`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await leasingFunnelPublic.submitApplication(token, {
        signature_type: 'typed',
        signature_data: signature,
        consent_agreed: true,
        field_values: values,
      });
      setApplication(res.data);
      setDone(true);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 409
          ? 'This application can no longer be submitted.'
          : status === 410
            ? 'This application link has expired.'
            : 'Failed to submit your application. Please try again.',
      );
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
        <Header
          variant="h1"
          description={application ? `For ${application.applicant_name}` : undefined}
        >
          {application?.title || 'Rental Application'}
        </Header>
      }
    >
      <Box padding={{ horizontal: 'l' }}>
        <SpaceBetween size="l">
          {error && <Alert type="error">{error}</Alert>}

          {done && (
            <Alert type="success" header="Thank you">
              Your application has been submitted. You may close this window.
            </Alert>
          )}

          {application?.body && (
            <Container header={<Header variant="h2">Application</Header>}>
              <Box variant="p">
                <span style={{ whiteSpace: 'pre-wrap' }}>{application.body}</span>
              </Box>
            </Container>
          )}

          {!done && (
            <>
              {(application?.field_schema ?? []).length > 0 && (
                <Container header={<Header variant="h2">Your information</Header>}>
                  <SpaceBetween size="m">
                    {(application?.field_schema ?? []).map((f) => (
                      <FormField
                        key={f.key}
                        label={f.label + (f.required ? ' *' : '')}
                      >
                        {f.type === 'textarea' ? (
                          <Textarea
                            value={values[f.key] ?? ''}
                            onChange={({ detail }) => setValue(f.key, detail.value)}
                          />
                        ) : (
                          <Input
                            type={f.type === 'number' ? 'number' : 'text'}
                            value={values[f.key] ?? ''}
                            onChange={({ detail }) => setValue(f.key, detail.value)}
                          />
                        )}
                      </FormField>
                    ))}
                  </SpaceBetween>
                </Container>
              )}

              <Container header={<Header variant="h2">Sign electronically</Header>}>
                <SpaceBetween size="m">
                  <FormField
                    label="Signature"
                    description="Type your full legal name to sign."
                  >
                    <Input
                      value={signature}
                      onChange={(e) => setSignature(e.detail.value)}
                    />
                  </FormField>
                  <Checkbox
                    checked={consent}
                    onChange={(e) => setConsent(e.detail.checked)}
                  >
                    {application?.consent_text}
                  </Checkbox>
                  <Button
                    variant="primary"
                    onClick={submit}
                    loading={submitting}
                    disabled={!consent}
                  >
                    Submit application
                  </Button>
                </SpaceBetween>
              </Container>
            </>
          )}
        </SpaceBetween>
      </Box>
    </ContentLayout>
  );
};

export default ApplicationPage;
