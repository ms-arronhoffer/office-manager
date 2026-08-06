import React, { useEffect, useRef, useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import { useAuth } from '@/auth/AuthContext';
import { auth as authApi } from '@/api';

const SESSION_CHECK_MS = 25 * 60 * 1000;

const SessionTimeoutWarning: React.FC = () => {
  const { logout } = useAuth();
  const [showWarning, setShowWarning] = useState(false);
  const [extending, setExtending] = useState(false);
  const warnTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const expireTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleTimers = () => {
    if (warnTimerRef.current) clearTimeout(warnTimerRef.current);
    if (expireTimerRef.current) clearTimeout(expireTimerRef.current);

    warnTimerRef.current = setTimeout(() => setShowWarning(true), SESSION_CHECK_MS);
  };

  useEffect(() => {
    scheduleTimers();
    return () => {
      if (warnTimerRef.current) clearTimeout(warnTimerRef.current);
      if (expireTimerRef.current) clearTimeout(expireTimerRef.current);
    };
  }, []);

  const handleExtend = async () => {
    setExtending(true);
    try {
      await authApi.refreshToken();
      setShowWarning(false);
      scheduleTimers();
    } catch {
      logout();
    } finally {
      setExtending(false);
    }
  };

  if (!showWarning) return null;

  return (
    <Modal
      visible
      header="Session Expiring Soon"
      onDismiss={handleExtend}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={logout}>Log Out</Button>
            <Button variant="primary" loading={extending} onClick={handleExtend}>
              Extend Session
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      Your session is about to expire. Click &quot;Extend Session&quot; to stay logged in.
    </Modal>
  );
};

export default SessionTimeoutWarning;
