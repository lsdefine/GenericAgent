import { readFileSync } from 'node:fs';

export interface E2EContextFile {
  mode: 'browser' | 'desktop';
  sandboxRoot: string;
  reports: string;
  bridgeBase: string;
  viteUrl?: string;
  controlBase: string;
  controlToken: string;
  application?: string;
  appEnv?: Record<string, string>;
}

export function loadE2EContext(): E2EContextFile {
  const path = process.env.GA_E2E_CONTEXT_FILE;
  if (!path) throw new Error('GA_E2E_CONTEXT_FILE is not set; use an e2e:* npm command');
  return JSON.parse(readFileSync(path, 'utf8')) as E2EContextFile;
}

export async function controlRequest<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const context = loadE2EContext();
  const response = await fetch(`${context.controlBase}${path}`, {
    ...init,
    headers: {
      'content-type': 'application/json',
      'x-ga-e2e-token': context.controlToken,
      ...init.headers,
    },
  });
  if (!response.ok) throw new Error(`Harness control ${path} failed: HTTP ${response.status} ${await response.text()}`);
  return await response.json() as T;
}
