// @vitest-environment node
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { cleanupSandbox, createSandbox } from './sandbox';

describe('isolated GenericAgent sandbox', () => {
  it('copies only selected workspace files and replaces credentials with loopback fake config', async () => {
    const source = await mkdtemp(join(tmpdir(), 'ga-e2e-source-'));
    await mkdir(join(source, 'frontends'), { recursive: true });
    await writeFile(join(source, 'agentmain.py'), '# current working tree\n');
    await writeFile(join(source, 'mykey.py'), "apikey = 'real-secret'\n");
    await writeFile(join(source, 'frontends', 'desktop_bridge.py'), '# bridge\n');

    const sandbox = await createSandbox({
      repoRoot: source,
      files: ['agentmain.py', 'mykey.py', 'frontends/desktop_bridge.py'],
      pythonPath: '/usr/bin/python3',
      fakeBaseUrl: 'http://127.0.0.1:23456',
      bridgePort: 24168,
      vitePort: 25173,
      controlToken: 'random-control-token',
    });

    expect(await readFile(join(sandbox.root, 'agentmain.py'), 'utf8')).toContain('current working tree');
    const mykey = await readFile(join(sandbox.root, 'mykey.py'), 'utf8');
    expect(mykey).toContain('http://127.0.0.1:23456/v1');
    expect(mykey).not.toContain('real-secret');
    expect(sandbox.env.HOME).toBe(sandbox.home);
    expect(sandbox.env.USERPROFILE).toBe(sandbox.home);
    expect(sandbox.env.GA_E2E_SETTINGS_PATH).toBe(join(sandbox.home, '.ga_desktop_settings.json'));
    expect(sandbox.env.BRIDGE_PORT).toBe('24168');
    expect(sandbox.env.VITE_BRIDGE_BASE).toBe('http://127.0.0.1:24168');
    expect(sandbox.env.GA_E2E_CONTROL_TOKEN).toBe('random-control-token');

    await cleanupSandbox(sandbox.root);
  });

  it('refuses non-loopback fake providers before creating a sandbox', async () => {
    await expect(createSandbox({
      repoRoot: process.cwd(),
      files: [],
      pythonPath: '/usr/bin/python3',
      fakeBaseUrl: 'https://api.example.com',
      bridgePort: 24168,
      vitePort: 25173,
      controlToken: 'token',
    })).rejects.toThrow(/loopback/i);
  });
});
