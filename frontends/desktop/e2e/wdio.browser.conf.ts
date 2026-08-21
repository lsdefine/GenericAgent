import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadE2EContext } from './harness/context';

const context = loadE2EContext();
if (!context.viteUrl) throw new Error('Browser E2E context is missing viteUrl');
const e2eRoot = dirname(fileURLToPath(import.meta.url));

export const config: WebdriverIO.Config = {
  runner: 'local',
  specs: [join(e2eRoot, 'specs', 'browser', '**', '*.e2e.ts')],
  maxInstances: 1,
  logLevel: 'error',
  bail: 0,
  baseUrl: context.viteUrl,
  waitforTimeout: 10_000,
  connectionRetryTimeout: 60_000,
  connectionRetryCount: 0,
  services: [[
    '@wdio/tauri-service',
    { mode: 'browser', devServerUrl: context.viteUrl, logLevel: 'error' },
  ]],
  capabilities: [{
    browserName: 'tauri',
    'goog:chromeOptions': {
      args: ['--headless=new', '--disable-gpu', '--no-sandbox', '--window-size=1440,1000'],
    },
  } as WebdriverIO.Capabilities],
  framework: 'mocha',
  reporters: ['spec'],
  mochaOpts: { ui: 'bdd', timeout: 60_000 },
  afterTest: async function (test, _context, result) {
    if (result.passed) return;
    mkdirSync(context.reports, { recursive: true });
    const safeName = test.title.replace(/[^a-z0-9_-]+/gi, '-').slice(0, 80);
    await browser.saveScreenshot(join(context.reports, `${safeName}.png`));
    writeFileSync(join(context.reports, `${safeName}.html`), await browser.getPageSource(), 'utf8');
  },
};
