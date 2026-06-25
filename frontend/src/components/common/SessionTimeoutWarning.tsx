import React, { useEffect, useRef, useState } from 'react';
import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import { useAuth } from '@/auth/AuthContext';
import { auth as authApi } from '@/api';

const WARNING_BEFORE_MS = 2 * 60 * 1000; // 2 minutes

function getTokenExpiry(): number | null {
  const token = localStorage.getItem('access_token');
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

const SessionTimeoutWarning: React.FC = () => {
  const { logout } = useAuth();
  const [showWarning, setShowWarning] = useState(false);
  const [extending, setExtending] = useState(false);
  const warnTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const expireTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleTimers = () => {
    if (warnTimerRef.current) clearTimeout(warnTimerRef.current);
    if (expireTimerRef.current) clearTimeout(expireTimerRef.current);

    const expiry = getTokenExpiry();
    if (!expiry) return;

    const now = Date.now();
    const msUntilExpiry = expiry - now;
    const msUntilWarning = msUntilExpiry - WARNING_BEFORE_MS;

    if (msUntilWarning > 0) {
      warnTimerRef.current = setTimeout(() => setShowWarning(true), msUntilWarning);
    } else if (msUntilExpiry > 0) {
      setShowWarning(true);
    }

    if (msUntilExpiry > 0) {
      expireTimerRef.current = setTimeout(() => {
        setShowWarning(false);
        logout();
      }, msUntilExpiry);
    }
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
      const res = await authApi.refreshToken();
      localStorage.setItem('access_token', res.data.access_token);
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
