import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Container from '@cloudscape-design/components/container';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Alert from '@cloudscape-design/components/alert';
import Spinner from '@cloudscape-design/components/spinner';
import { emailAckPublic, type EmailAckView } from '@/api';

const AckPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const [view, setView] = useState<EmailAckView | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await emailAckPublic.view(token);
      setView(data);
    } catch {
      setError('This acknowledgement link is invalid or has expired.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const confirm = async () => {
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      const { data } = await emailAckPublic.confirm(token);
      setView(data);
    } catch {
      setError('Unable to record your acknowledgement. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ContentLayout header={<Header variant="h1">Acknowledge Reminder</Header>}>
      <Container>
        {loading ? (
          <Box textAlign="center" padding="l">
            <Spinner size="large" />
          </Box>
        ) : error ? (
          <Alert type="error">{error}</Alert>
        ) : view ? (
          <SpaceBetween size="m">
            {view.rule_name && (
              <Box variant="awsui-key-label">Reminder rule: {view.rule_name}</Box>
            )}
            <Box variant="h3">{view.subject}</Box>
            {view.acknowledged ? (
              <Alert type="success">
                This reminder has been acknowledged
                {view.acknowledged_at ? ` on ${new Date(view.acknowledged_at).toLocaleString()}` : ''}.
                No further escalation emails will be sent.
              </Alert>
            ) : (
              <SpaceBetween size="s">
                <Box variant="p">
                  Confirm that this reminder has been actioned so it stops escalating.
                </Box>
                <Button variant="primary" loading={submitting} onClick={confirm}>
                  Acknowledge
                </Button>
              </SpaceBetween>
            )}
          </SpaceBetween>
        ) : null}
      </Container>
    </ContentLayout>
  );
};

export default AckPage;
