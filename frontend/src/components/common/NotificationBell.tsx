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

/**
 * aria-label used by the notification trigger button. The panel uses it to
 * detect clicks on the trigger so an outside-click doesn't fight the button's
 * own toggle handler. When there are unread items the button appends a count,
 * so both exact and " (" prefixed forms are matched.
 */
export const NOTIFICATION_TRIGGER_LABEL = 'Notifications';

/** CSS selector matching only the notification trigger button's aria-label. */
const NOTIFICATION_TRIGGER_SELECTOR =
  `[aria-label="${NOTIFICATION_TRIGGER_LABEL}"],` +
  `[aria-label^="${NOTIFICATION_TRIGGER_LABEL} ("]`;

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export interface UseNotifications {
  unreadCount: number;
  panelOpen: boolean;
  setPanelOpen: React.Dispatch<React.SetStateAction<boolean>>;
  items: NotificationItem[];
  handleItemClick: (item: NotificationItem) => void;
  handleMarkAllRead: () => void;
  handleClearAll: () => void;
}

/**
 * Encapsulates notification state (unread count, list, live push, polling) so
 * the trigger can be rendered as a Cloudscape TopNavigation utility button
 * while the dropdown panel is rendered separately via {@link NotificationPanel}.
 */
export function useNotifications(): UseNotifications {
  const navigate = useNavigate();
  const { addMessageHandler } = useWS();
  const [unreadCount, setUnreadCount] = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);

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

  const handleItemClick = useCallback(async (item: NotificationItem) => {
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
  }, [navigate]);

  const handleMarkAllRead = useCallback(async () => {
    try {
      await notificationsApi.markAllRead();
      setUnreadCount(0);
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch { /* silent */ }
  }, []);

  const handleClearAll = useCallback(async () => {
    try {
      await notificationsApi.clearAll();
      setUnreadCount(0);
      setItems([]);
    } catch { /* silent */ }
  }, []);

  return {
    unreadCount,
    panelOpen,
    setPanelOpen,
    items,
    handleItemClick,
    handleMarkAllRead,
    handleClearAll,
  };
}

export interface NotificationPanelProps {
  open: boolean;
  onClose: () => void;
  unreadCount: number;
  items: NotificationItem[];
  onItemClick: (item: NotificationItem) => void;
  onMarkAllRead: () => void;
  onClearAll: () => void;
}

/**
 * The notification dropdown panel. Rendered independently of the trigger button
 * (which lives in the TopNavigation utilities) and anchored to the top-right of
 * the viewport, just under the nav bar.
 */
export const NotificationPanel: React.FC<NotificationPanelProps> = ({
  open,
  onClose,
  unreadCount,
  items,
  onItemClick,
  onMarkAllRead,
  onClearAll,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);

  // Close panel on outside click, ignoring clicks on the trigger button so it
  // can toggle the panel itself without immediately reopening.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (panelRef.current && panelRef.current.contains(target)) return;
      if (target.closest(NOTIFICATION_TRIGGER_SELECTOR)) return;
      onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={panelRef}
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
            <Button variant="link" onClick={onMarkAllRead}>
              Mark all read
            </Button>
          )}
          {items.length > 0 && (
            <Button variant="link" onClick={onClearAll}>
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
            onClick={() => onItemClick(item)}
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
  );
};

export default NotificationPanel;
