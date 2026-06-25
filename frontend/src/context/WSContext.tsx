import React, { createContext, useContext, useEffect, useRef, useCallback, useState } from 'react';

export type WSMessage =
  | { type: 'notification'; notification: NotificationPayload }
  | { type: 'ticket_updated'; ticket_id: string; status: string }
  | { type: 'presence_update'; entity_type: string; entity_id: string; viewers: string[] }
  | { type: 'pong' };

export interface NotificationPayload {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  entity_type: string | null;
  entity_id: string | null;
  is_read: boolean;
  created_at: string | null;
}

type MessageHandler = (msg: WSMessage) => void;

interface WSContextValue {
  connected: boolean;
  sendPresence: (entityType: string, entityId: string) => void;
  clearPresence: () => void;
  addMessageHandler: (handler: MessageHandler) => () => void;
}

const WSContext = createContext<WSContextValue>({
  connected: false,
  sendPresence: () => {},
  clearPresence: () => {},
  addMessageHandler: () => () => {},
});

const WS_BASE = (() => {
  const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1';
  // Build WebSocket URL from the API base
  const loc = window.location;
  const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
  if (apiBase.startsWith('http')) {
    return apiBase.replace(/^https?/, proto === 'wss:' ? 'wss' : 'ws');
  }
  return `${proto}//${loc.host}`;
})();

export const WSProvider: React.FC<{ children: React.ReactNode; token: string | null }> = ({
  children,
  token,
}) => {
  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef<Set<MessageHandler>>(new Set());
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [connected, setConnected] = useState(false);

  const dispatch = useCallback((msg: WSMessage) => {
    handlersRef.current.forEach((h) => h(msg));
  }, []);

  const connect = useCallback(() => {
    if (!token) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const url = `${WS_BASE}/ws/connect?token=${token}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        dispatch(msg);
      } catch {
        // ignore malformed
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Reconnect after 3 seconds
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [token, dispatch]);

  useEffect(() => {
    if (!token) return;
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [token, connect]);

  const sendPresence = useCallback((entityType: string, entityId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'presence', entity_type: entityType, entity_id: entityId }));
    }
  }, []);

  const clearPresence = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'presence', entity_type: '', entity_id: '' }));
    }
  }, []);

  const addMessageHandler = useCallback((handler: MessageHandler) => {
    handlersRef.current.add(handler);
    return () => handlersRef.current.delete(handler);
  }, []);

  return (
    <WSContext.Provider value={{ connected, sendPresence, clearPresence, addMessageHandler }}>
      {children}
    </WSContext.Provider>
  );
};

export const useWS = () => useContext(WSContext);
