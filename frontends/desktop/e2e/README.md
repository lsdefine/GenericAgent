# GenericAgent Desktop E2E Harness

The desktop harness drives both Chrome and the real Tauri application with WebdriverIO. Both modes use the same deterministic fake OpenAI server, semantic page objects, isolated product sandbox, and token assertions.

## Commands

Run from `frontends/desktop` after `npm ci`:

```bash
npm run e2e:doctor
npm run e2e:browser
npm run e2e:desktop
npm run e2e:desktop:full
```

`e2e:browser` is the fast PR journey. It sends messages through the real UI and bridge, verifies exact per-call usage, corrupt-tail tolerance, restart persistence, localized empty replies, and a hard crash while the second model call is in flight.

`e2e:desktop` builds the application with Cargo's `e2e` feature and `src-tauri/tauri.e2e.conf.json`, then drives the native window. It verifies sandbox identity, chat, usage, bridge-offline UI, and recovery through the real Tauri `start_bridge` command. Linux needs a display; CI uses `xvfb-run -a`.

`e2e:desktop:full` additionally places an identified foreign listener on the isolated bridge port, verifies that the native launcher refuses to take it over, then releases the port and retries recovery through the UI. It is reserved for nightly/manual runs.

The real-model canary is intentionally separate from merge gates:

```bash
GA_E2E_CANARY_BASE=https://provider.example \
GA_E2E_CANARY_KEY=... \
GA_E2E_CANARY_MODEL=low-cost-model \
npm run e2e:canary
```

## Isolation and safety

Every run creates a sentinel-protected temporary root and copies the current tracked and untracked product files, excluding developer metadata and build outputs. The harness creates isolated HOME/settings, `mykey.py`, sessions, uploads, ledger, reports, dynamic ports, and a random control token. The bridge identity must resolve to that exact root before a browser journey can continue.

PR runs reject non-loopback fake-model URLs. Model credentials are dummy values. Control routes require `GA_E2E=1`, a random `X-GA-E2E-Token`, and a loopback peer. They do not exist in normal bridge startup.

The WDIO Rust plugins are optional Cargo dependencies enabled only by the `e2e` feature. The frontend plugin is included only when `VITE_GA_E2E=1`. `npm run test:e2e-isolation` builds production assets and fails if WDIO markers remain.

## Failure evidence

Failed runs retain their sentinel sandbox and copy redacted reports to `frontends/desktop/e2e-results/`. Evidence includes screenshots, page source, bridge/Vite logs, bootstrap snapshots, endpoint snapshots, fake-model request timing, ledger data, PIDs, and ports. Authorization and key-bearing log lines are replaced before writing.

Set `GA_E2E_PYTHON` when automatic Python discovery cannot find a runtime with `aiohttp`. Set `GA_E2E_ARTIFACT_DIR` to change the stable report-copy destination. `GA_E2E_APPLICATION` may point to an already-built binary only when that binary was compiled with the same `VITE_BRIDGE_BASE`; normal use should let `e2e:desktop` build it after allocating ports.

## Validation topology

- Pull requests: TypeScript, Vitest, Python ledger/process contracts, Rust production/E2E feature tests, production isolation, browser E2E, and Linux native Tauri smoke.
- P2 candidate: native Tauri validation plus real Windows ZIP, Ubuntu tar/AppImage, and macOS DMG journeys. Platform wrappers are under `e2e/windows/`, `e2e/linux/`, and `e2e/macos/`; `e2e/package/` enforces their common production and evidence contract.
- Manual only: the credentialed real-model protocol canary, which never blocks P2. No fork-only nightly workflow is part of the PR.
