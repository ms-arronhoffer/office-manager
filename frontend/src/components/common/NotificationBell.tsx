import React, { useState, useEffect, useCallback, useRef } from 'react';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import { useNavigate } from 'react-router-dom';
import { notifications as notificationsApi } from '@/api';
import { useWS } from '@/context/WSContext';
import type { NotificationItem } from '@/types';

const ENTITY_PATHS: Record<string, string> = {
  ticket: '/maintenance-tickets',
  lease: '/leases',
  hvac_contract: '/hvac-contracts',
};

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const NotificationBell: React.FC = () => {
  const navigate = useNavigate();
  const { addMessageHandler } = useWS();
  const [unreadCount, setUnreadCount] = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchCount = useCallback(async () => {
    try {
      const resp = await notificationsApi.count();
      setUnreadCount(resp.data.unread);
    } catch { /* silent */ }
  }, []);

  const fetchList = useCallback(async () => {
    try {
      const resp = await notificationsApi.list();
      setItems(resp.data.slice(0, 10));
    } catch { /* silent */ }
  }, []);

  // WebSocket: live push for new notifications
  useEffect(() => {
    return addMessageHandler((msg) => {
      if (msg.type === 'notification') {
        setUnreadCount((c) => c + 1);
        const n = msg.notification;
        setItems((prev) => [
          {
            id: n.id,
            kind: n.kind,
            title: n.title,
            body: n.body,
            entity_type: n.entity_type,
            entity_id: n.entity_id,
            is_read: false,
            created_at: n.created_at ?? new Date().toISOString(),
          },
          ...prev,
        ].slice(0, 10));
      }
    });
  }, [addMessageHandler]);

  // Poll for unread count every 60 s (fallback when WS is disconnected)
  useEffect(() => {
    fetchCount();
    const interval = setInterval(fetchCount, 60_000);
    return () => clearInterval(interval);
  }, [fetchCount]);

  // Load list whenever panel opens
  useEffect(() => {
    if (panelOpen) fetchList();
  }, [panelOpen, fetchList]);

  // Close panel on outside click
  useEffect(() => {
    if (!panelOpen) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setPanelOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [panelOpen]);

  const handleItemClick = async (item: NotificationItem) => {
    if (!item.is_read) {
      try {
        await notificationsApi.markRead(item.id);
        setUnreadCount((c) => Math.max(0, c - 1));
        setItems((prev) => prev.map((n) => (n.id === item.id ? { ...n, is_read: true } : n)));
      } catch { /* silent */ }
    }
    const path = item.entity_type ? ENTITY_PATHS[item.entity_type] : null;
    if (path && item.entity_id) {
      navigate(`${path}/${item.entity_id}`);
      setPanelOpen(false);
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await notificationsApi.markAllRead();
      setUnreadCount(0);
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch { /* silent */ }
  };

  const handleClearAll = async () => {
    try {
      await notificationsApi.clearAll();
      setUnreadCount(0);
      setItems([]);
    } catch { /* silent */ }
  };

  return (
    <div
      ref={containerRef}
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
    >
      {/* Bell trigger */}
      <div style={{ position: 'relative' }}>
        <Button
          iconName="notification"
          variant="icon"
          ariaLabel={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
          onClick={() => setPanelOpen((o) => !o)}
        />
        {unreadCount > 0 && (
          <span
            aria-hidden="true"
            style={{
              position: 'absolute',
              top: 2,
              right: 2,
              background: '#d91515',
              color: '#fff',
              borderRadius: '50%',
              fontSize: 9,
              fontWeight: 700,
              minWidth: 15,
              height: 15,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 2px',
              pointerEvents: 'none',
              lineHeight: 1,
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </div>

      {/* Dropdown panel */}
      {panelOpen && (
        <div
          style={{
            position: 'fixed',
            top: 56,
            right: 80,
            width: 360,
            maxHeight: 480,
            overflowY: 'auto',
            background: 'var(--color-background-container-content, #ffffff)',
            border: '1px solid var(--color-border-divider-default, #c6c6cd)',
            borderRadius: 8,
            boxShadow: '0 4px 20px rgba(0,0,0,0.18)',
            zIndex: 2000,
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: '10px 14px',
              borderBottom: '1px solid var(--color-border-divider-default, #c6c6cd)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 13 }}>
              Notifications{unreadCount > 0 ? ` · ${unreadCount} unread` : ''}
            </span>
            <SpaceBetween direction="horizontal" size="xs">
              {unreadCount > 0 && (
                <Button variant="link" onClick={handleMarkAllRead}>
                  Mark all read
                </Button>
              )}
              {items.length > 0 && (
                <Button variant="link" onClick={handleClearAll}>
                  Clear
                </Button>
              )}
            </SpaceBetween>
          </div>

          {/* Body */}
          {items.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <Box color="text-status-inactive">No notifications</Box>
            </div>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                onClick={() => handleItemClick(item)}
                style={{
                  padding: '10px 14px',
                  borderBottom: '1px solid var(--color-border-divider-default, #eee)',
                  cursor:
                    item.entity_type && ENTITY_PATHS[item.entity_type] ? 'pointer' : 'default',
                  background: item.is_read
                    ? 'transparent'
                    : 'var(--color-background-notification-default, #f0f7ff)',
                }}
              >
                <div style={{ fontSize: 13, fontWeight: item.is_read ? 400 : 600 }}>
                  {item.title}
                </div>
                {item.body && (
                  <div
                    style={{
                      fontSize: 12,
                      color: 'var(--color-text-body-secondary, #5f6b7a)',
                      marginTop: 2,
                    }}
                  >
                    {item.body}
                  </div>
                )}
                <div
                  style={{
                    fontSize: 11,
                    color: 'var(--color-text-body-secondary, #5f6b7a)',
                    marginTop: 4,
                  }}
                >
                  {relativeTime(item.created_at)}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
