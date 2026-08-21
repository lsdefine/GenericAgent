// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { resolveServiceEndpoints } from '../services/constants';

describe('service endpoint configuration', () => {
  it('keeps production defaults and derives websocket URLs from the HTTP bases', () => {
    expect(resolveServiceEndpoints({})).toEqual({
      bridgeBase: 'http://127.0.0.1:14168',
      conductorBase: 'http://127.0.0.1:8900',
      wsUrl: 'ws://127.0.0.1:14168/ws',
      conductorWsUrl: 'ws://127.0.0.1:8900/ws',
    });
  });

  it('accepts isolated harness bases and normalizes trailing slashes', () => {
    expect(resolveServiceEndpoints({
      VITE_BRIDGE_BASE: 'http://127.0.0.1:24168/',
      VITE_CONDUCTOR_BASE: 'https://localhost:28900///',
    })).toEqual({
      bridgeBase: 'http://127.0.0.1:24168',
      conductorBase: 'https://localhost:28900',
      wsUrl: 'ws://127.0.0.1:24168/ws',
      conductorWsUrl: 'wss://localhost:28900/ws',
    });
  });

  it('rejects non-http endpoint schemes', () => {
    expect(() => resolveServiceEndpoints({ VITE_BRIDGE_BASE: 'file:///tmp/bridge' }))
      .toThrow(/http/i);
  });
});
