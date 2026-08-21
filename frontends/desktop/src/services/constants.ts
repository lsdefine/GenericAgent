interface ServiceEndpointEnv {
  VITE_BRIDGE_BASE?: string;
  VITE_CONDUCTOR_BASE?: string;
}

function normalizeHttpBase(value: string | undefined, fallback: string): string {
  const raw = value?.trim() || fallback;
  const url = new URL(raw);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(`Service endpoint must use HTTP(S): ${raw}`);
  }
  return url.toString().replace(/\/+$/, '');
}

function websocketUrl(httpBase: string): string {
  const url = new URL(httpBase);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/+$/, '')}/ws`;
  return url.toString().replace(/\/$/, '');
}

export function resolveServiceEndpoints(env: ServiceEndpointEnv) {
  const bridgeBase = normalizeHttpBase(env.VITE_BRIDGE_BASE, 'http://127.0.0.1:14168');
  const conductorBase = normalizeHttpBase(env.VITE_CONDUCTOR_BASE, 'http://127.0.0.1:8900');
  return {
    bridgeBase,
    conductorBase,
    wsUrl: websocketUrl(bridgeBase),
    conductorWsUrl: websocketUrl(conductorBase),
  };
}

const endpoints = resolveServiceEndpoints({
  VITE_BRIDGE_BASE: import.meta.env.VITE_BRIDGE_BASE,
  VITE_CONDUCTOR_BASE: import.meta.env.VITE_CONDUCTOR_BASE,
});

export const BRIDGE_BASE = endpoints.bridgeBase;
export const CONDUCTOR_BASE = endpoints.conductorBase;
export const WS_URL = endpoints.wsUrl;
export const CONDUCTOR_WS_URL = endpoints.conductorWsUrl;
