// @vitest-environment node
import { link, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  allocateLoopbackPort,
  assertLoopbackUrl,
  assertSandboxRoot,
  pathsReferToSameEntry,
  redactEvidence,
} from './runtime';

describe('E2E harness runtime safety', () => {
  it('accepts loopback services and rejects external endpoints', () => {
    expect(assertLoopbackUrl('http://127.0.0.1:1234/v1')).toBe('http://127.0.0.1:1234/v1');
    expect(assertLoopbackUrl('http://localhost:1234')).toBe('http://localhost:1234');
    expect(() => assertLoopbackUrl('https://api.example.com/v1')).toThrow(/loopback/i);
  });

  it('allocates currently available non-zero ports', async () => {
    const first = await allocateLoopbackPort();
    const second = await allocateLoopbackPort();
    expect(first).toBeGreaterThan(0);
    expect(second).toBeGreaterThan(0);
    expect(first).not.toBe(second);
  });

  it('requires the sandbox sentinel before destructive cleanup', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ga-e2e-runtime-'));
    expect(() => assertSandboxRoot(root)).toThrow(/sentinel/i);
    await writeFile(join(root, '.ga-e2e-sandbox'), 'v1\n');
    expect(assertSandboxRoot(root)).toBe(root);
    expect(await readFile(join(root, '.ga-e2e-sandbox'), 'utf8')).toBe('v1\n');
  });

  it('compares filesystem identity instead of path spelling', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ga-e2e-path-identity-'));
    const original = join(root, 'long-name');
    const alias = join(root, 'SHORT~1');
    const sibling = join(root, 'sibling');
    await writeFile(original, 'sandbox');
    await link(original, alias);
    await writeFile(sibling, 'different');

    expect(pathsReferToSameEntry(original, alias)).toBe(true);
    expect(pathsReferToSameEntry(original, sibling)).toBe(false);
  });

  it('redacts credentials without removing useful process evidence', () => {
    expect(redactEvidence('Authorization: Bearer secret\npid=42\napikey=abc')).toBe(
      '[redacted sensitive line]\npid=42\n[redacted sensitive line]',
    );
  });
});
