import { existsSync, realpathSync, statSync } from 'node:fs';
import { createServer } from 'node:net';
import { resolve } from 'node:path';

const allocatedPorts = new Set<number>();

export function assertLoopbackUrl(raw: string): string {
  const url = new URL(raw);
  const loopback = url.hostname === '127.0.0.1' || url.hostname === 'localhost' || url.hostname === '[::1]';
  if (!loopback || (url.protocol !== 'http:' && url.protocol !== 'https:')) {
    throw new Error(`E2E services must use an HTTP(S) loopback URL: ${raw}`);
  }
  return raw;
}

export async function allocateLoopbackPort(): Promise<number> {
  for (;;) {
    const port = await new Promise<number>((resolvePort, reject) => {
      const server = createServer();
      server.once('error', reject);
      server.listen(0, '127.0.0.1', () => {
        const address = server.address();
        const selected = typeof address === 'object' && address ? address.port : 0;
        server.close((error) => error ? reject(error) : resolvePort(selected));
      });
    });
    if (port > 0 && !allocatedPorts.has(port)) {
      allocatedPorts.add(port);
      return port;
    }
  }
}

export function assertSandboxRoot(root: string): string {
  const absolute = resolve(root);
  if (!existsSync(`${absolute}/.ga-e2e-sandbox`)) {
    throw new Error(`Refusing sandbox operation without sentinel: ${absolute}`);
  }
  return absolute;
}

export function pathsReferToSameEntry(left: string, right: string): boolean {
  try {
    const leftPath = realpathSync.native(resolve(left));
    const rightPath = realpathSync.native(resolve(right));
    const normalize = (path: string): string => process.platform === 'win32' ? path.toLowerCase() : path;
    if (normalize(leftPath) === normalize(rightPath)) return true;

    // Windows can preserve an 8.3 spelling (RUNNER~1) for one caller while another reports
    // the long path (runneradmin). Device + inode compare the directory identity without
    // weakening the sandbox boundary to prefix or case-only checks.
    const leftIdentity = statSync(leftPath, { bigint: true });
    const rightIdentity = statSync(rightPath, { bigint: true });
    return leftIdentity.ino !== 0n
      && leftIdentity.dev === rightIdentity.dev
      && leftIdentity.ino === rightIdentity.ino;
  } catch {
    return false;
  }
}

export function redactEvidence(text: string): string {
  return text.split(/\r?\n/).map((line) => {
    const lower = line.toLowerCase();
    return ['authorization', 'bearer', 'apikey', 'api_key', 'secret'].some((marker) => lower.includes(marker))
      ? '[redacted sensitive line]'
      : line;
  }).join('\n');
}
