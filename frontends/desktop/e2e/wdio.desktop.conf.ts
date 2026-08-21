import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadE2EContext } from './harness/context';

const context = loadE2EContext();
if (!context.application) throw new Error('Desktop E2E context is missing application path');
const e2eRoot = dirname(fileURLToPath(import.meta.url));
const smokeSpec = join(e2eRoot, 'specs', 'desktop', 'smoke.e2e.ts');
const fullSpec = join(e2eRoot, 'specs', 'desktop', 'full.e2e.ts');

export const config: WebdriverIO.Config = {
  runner: 'local',
  specs: process.env.GA_E2E_SUITE === 'full' ? [smokeSpec, fullSpec] : [smokeSpec],
  maxInstances: 1,
  logLevel: 'error',
  bail: 0,
  waitforTimeout: 15_000,
  connectionRetryTimeout: 90_000,
  connectionRetryCount: 0,
  services: [[
    '@wdio/tauri-service',
    {
      appBinaryPath: context.application,
      driverProvider: 'embedded',
      logLevel: 'error',
      env: context.appEnv,
      captureBackendLogs: true,
      captureFrontendLogs: true,
      logDir: context.reports,
      startTimeout: 60_000,
    },
  ]],
  capabilities: [{
    browserName: 'tauri',
    'tauri:options': { application: context.application },
  } as WebdriverIO.Capabilities],
  framework: 'mocha',
  reporters: ['spec'],
  mochaOpts: { ui: 'bdd', timeout: 90_000 },
  afterTest: async function (test, _context, result) {
    if (result.passed) return;
    mkdirSync(context.reports, { recursive: true });
    const safeName = test.title.replace(/[^a-z0-9_-]+/gi, '-').slice(0, 80);
    await browser.saveScreenshot(join(context.reports, `${safeName}.png`));
    writeFileSync(join(context.reports, `${safeName}.html`), await browser.getPageSource(), 'utf8');
  },
};
