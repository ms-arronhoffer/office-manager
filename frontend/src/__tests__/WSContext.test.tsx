import React from 'react';
import { render, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { WSProvider, useWS } from '@/context/WSContext';

// Minimal controllable WebSocket mock so we can drive open/close events.
class MockWebSocket {
  static OPEN = 1;
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  readyState = 0;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    /* no-op; tests trigger onclose manually */
  }

  send() {
    /* no-op */
  }
}

const Consumer: React.FC = () => {
  const { connected } = useWS();
  return <div data-testid="status">{connected ? 'connected' : 'disconnected'}</div>;
};

describe('WSProvider reconnect behavior', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('does not reconnect when no token is present', () => {
    render(
      <WSProvider token={null}>
        <Consumer />
      </WSProvider>,
    );
    expect(MockWebSocket.instances).toHaveLength(0); // no socket created
  });

  it('reconnects with backoff after a non-auth close', () => {
    render(
      <WSProvider token="abc">
        <Consumer />
      </WSProvider>,
    );
    expect(MockWebSocket.instances).toHaveLength(1);

    // Simulate the backend being unavailable: socket closes with a generic code.
    act(() => {
      MockWebSocket.instances[0].onclose?.({ code: 1006 });
    });

    // No immediate reconnect — it is scheduled behind a backoff delay.
    expect(MockWebSocket.instances).toHaveLength(1);

    // Advance beyond the max backoff to guarantee the retry fires.
    act(() => {
      vi.advanceTimersByTime(31000);
    });
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('stops reconnecting when the server rejects the token (4001)', () => {
    render(
      <WSProvider token="stale">
        <Consumer />
      </WSProvider>,
    );
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => {
      MockWebSocket.instances[0].onclose?.({ code: 4001 });
    });

    // Even after a long time, no reconnect attempt is made.
    act(() => {
      vi.advanceTimersByTime(120000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
