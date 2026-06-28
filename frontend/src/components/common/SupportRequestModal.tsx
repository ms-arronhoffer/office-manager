import React, { useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import Form from '@cloudscape-design/components/form';
import FormField from '@cloudscape-design/components/form-field';
import Input from '@cloudscape-design/components/input';
import Textarea from '@cloudscape-design/components/textarea';
import Alert from '@cloudscape-design/components/alert';
import { supportRequests } from '@/api';

interface SupportRequestModalProps {
  visible: boolean;
  onDismiss: () => void;
}

/**
 * Global "Contact support" form. Any authenticated user can submit a support
 * request; the entry is stored and surfaced on the Administration → Support
 * Requests page (and forwarded to the configured support email).
 */
const SupportRequestModal: React.FC<SupportRequestModalProps> = ({ visible, onDismiss }) => {
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const reset = () => {
    setSubject('');
    setMessage('');
    setError(null);
    setSuccess(false);
  };

  const handleDismiss = () => {
    reset();
    onDismiss();
  };

  const handleSubmit = async () => {
    if (!subject.trim() || !message.trim()) {
      setError('Both a subject and a message are required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await supportRequests.create({ subject: subject.trim(), message: message.trim() });
      setSuccess(true);
      setSubject('');
      setMessage('');
    } catch {
      setError('Failed to submit support request. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      visible={visible}
      header="Support request"
      onDismiss={handleDismiss}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={handleDismiss} disabled={submitting}>
              {success ? 'Close' : 'Cancel'}
            </Button>
            {!success && (
              <Button
                variant="primary"
                onClick={handleSubmit}
                loading={submitting}
                disabled={!subject.trim() || !message.trim()}
              >
                Submit
              </Button>
            )}
          </SpaceBetween>
        </Box>
      }
    >
      <Form>
        <SpaceBetween size="m">
          {error && <Alert type="error">{error}</Alert>}
          {success ? (
            <Alert type="success">
              Your support request has been submitted. An administrator will review it shortly.
            </Alert>
          ) : (
            <>
              <Box variant="p" color="text-body-secondary">
                Describe the issue or request and our team will follow up.
              </Box>
              <FormField label="Subject">
                <Input
                  value={subject}
                  onChange={({ detail }) => setSubject(detail.value)}
                  placeholder="Brief summary of your request"
                />
              </FormField>
              <FormField label="Message">
                <Textarea
                  value={message}
                  onChange={({ detail }) => setMessage(detail.value)}
                  placeholder="Provide as much detail as possible"
                  rows={5}
                />
              </FormField>
            </>
          )}
        </SpaceBetween>
      </Form>
    </Modal>
  );
};

export default SupportRequestModal;
