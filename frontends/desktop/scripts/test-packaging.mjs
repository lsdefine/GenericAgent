#!/usr/bin/env node
/**
 * test-packaging.mjs — Pre-packaging validation.
 *
 * Verifies that packaging prerequisites are in order before attempting
 * a Tauri build. Checks tauri.conf.json semantics, icon file existence,
 * and packaging script syntax.
 *
 * Usage:
 *   node scripts/test-packaging.mjs
 *
 * Exit codes:
 *   0 = all checks pass
 *   1 = one or more checks failed
 */
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DESKTOP_ROOT = path.resolve(__dirname, '..');
const TAURI_DIR = path.join(DESKTOP_ROOT, 'src-tauri');
const PACKAGING_DIR = path.join(DESKTOP_ROOT, 'packaging');

let pass = 0;
let fail = 0;
const warnings = [];
const RELEASE_VERSION = '0.2.0';

function ok(msg) { console.log(`  ✓ ${msg}`); pass++; }
function bad(msg) { console.error(`  ✗ ${msg}`); fail++; }
function warn(msg) { console.warn(`  ⚠ ${msg}`); warnings.push(msg); }

// ── 1. tauri.conf.json validation ──
console.log('\n[1] tauri.conf.json');

const confPath = path.join(TAURI_DIR, 'tauri.conf.json');
if (!fs.existsSync(confPath)) {
  bad('tauri.conf.json not found');
} else {
  let conf;
  try {
    conf = JSON.parse(fs.readFileSync(confPath, 'utf8'));
    ok('tauri.conf.json is valid JSON');
  } catch (e) {
    bad(`tauri.conf.json parse error: ${e.message}`);
  }

  if (conf) {
    if (conf.productName && conf.productName.length > 0) {
      ok(`productName: "${conf.productName}"`);
    } else {
      bad('productName is missing or empty');
    }

    if (conf.version && /^\d+\.\d+\.\d+/.test(conf.version)) {
      ok(`version: ${conf.version}`);
    } else {
      bad(`version "${conf.version}" is not semver`);
    }

    if (conf.build?.frontendDist) {
      ok(`frontendDist: ${conf.build.frontendDist}`);
    } else {
      bad('build.frontendDist is not set');
    }

    if (conf.bundle?.targets?.length > 0) {
      ok(`bundle targets: [${conf.bundle.targets.join(', ')}]`);
    } else {
      warn('no bundle targets specified');
    }
  }
}

// ── 2. Icon files ──
console.log('\n[2] Icon files');

const iconsDir = path.join(TAURI_DIR, 'icons');
if (!fs.existsSync(iconsDir)) {
  bad('src-tauri/icons/ directory not found');
} else {
  const confIcons = JSON.parse(fs.readFileSync(confPath, 'utf8')).bundle?.icon || [];
  let allFound = true;
  for (const iconRef of confIcons) {
    const iconPath = path.join(TAURI_DIR, iconRef);
    if (fs.existsSync(iconPath)) {
      ok(`icon exists: ${iconRef}`);
    } else {
      bad(`icon missing: ${iconRef}`);
      allFound = false;
    }
  }
  if (confIcons.length === 0) {
    warn('no icons specified in bundle.icon');
  }
}

// ── 3. Packaging scripts syntax ──
console.log('\n[3] Packaging scripts');

const scriptsDir = path.join(PACKAGING_DIR, 'scripts');
if (!fs.existsSync(scriptsDir)) {
  warn('packaging/scripts/ not found');
} else {
  const shScripts = [];
  for (const platform of ['linux', 'macos', 'windows']) {
    const dir = path.join(scriptsDir, platform);
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir)) {
      if (f.endsWith('.sh')) shScripts.push(path.join(dir, f));
    }
  }

  for (const script of shScripts) {
    try {
      execSync(`bash -n "${script}" 2>&1`, { timeout: 5000 });
      ok(`syntax OK: ${path.relative(DESKTOP_ROOT, script)}`);
    } catch (e) {
      bad(`syntax error: ${path.relative(DESKTOP_ROOT, script)}\n    ${e.stdout?.toString().trim() || e.message}`);
    }
  }

  for (const relative of [
    'e2e/linux/Invoke-LinuxUserJourney.sh',
    'e2e/macos/Invoke-macOSUserJourney.sh',
  ]) {
    const script = path.join(DESKTOP_ROOT, relative);
    try {
      execFileSync('bash', ['-n', script], { timeout: 5000 });
      ok(`syntax OK: ${relative}`);
    } catch (e) {
      bad(`syntax error: ${relative}\n    ${e.stderr?.toString().trim() || e.message}`);
    }
  }

  for (const relative of [
    'e2e/package/real_package_journey.py',
    'e2e/package/verify_candidate_evidence.py',
  ]) {
    const script = path.join(DESKTOP_ROOT, relative);
    try {
      execFileSync('python3', [script, '--help'], { timeout: 5000, stdio: 'ignore' });
      ok(`CLI contract OK: ${relative}`);
    } catch (e) {
      bad(`CLI contract failed: ${relative}: ${e.message}`);
    }
  }
}

// ── 4. Release version consistency ──
console.log('\n[4] Version consistency');

const cargoPath = path.join(TAURI_DIR, 'Cargo.toml');
const cargoLockPath = path.join(TAURI_DIR, 'Cargo.lock');
const packagePath = path.join(DESKTOP_ROOT, 'package.json');
const packageLockPath = path.join(DESKTOP_ROOT, 'package-lock.json');
if (fs.existsSync(cargoPath) && fs.existsSync(cargoLockPath) && fs.existsSync(confPath) && fs.existsSync(packagePath) && fs.existsSync(packageLockPath)) {
  const cargoContent = fs.readFileSync(cargoPath, 'utf8');
  const cargoVersion = cargoContent.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  const cargoLock = fs.readFileSync(cargoLockPath, 'utf8');
  const cargoLockVersion = cargoLock.match(/\[\[package\]\]\s+name = "ga-desktop"\s+version = "([^"]+)"/m)?.[1];
  const tauriConf = JSON.parse(fs.readFileSync(confPath, 'utf8'));
  const packageJson = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  const packageLock = JSON.parse(fs.readFileSync(packageLockPath, 'utf8'));
  const versions = {
    'package.json': packageJson.version,
    'package-lock.json': packageLock.version,
    'package-lock root': packageLock.packages?.['']?.version,
    'Cargo.toml': cargoVersion,
    'Cargo.lock ga-desktop': cargoLockVersion,
    'tauri.conf.json': tauriConf.version,
  };
  for (const [source, version] of Object.entries(versions)) {
    if (version === RELEASE_VERSION) {
      ok(`${source} version is ${RELEASE_VERSION}`);
    } else {
      bad(`${source} version is ${version ?? 'missing'}; expected ${RELEASE_VERSION}`);
    }
  }
}

// ── Summary ──
console.log(`\n=== Results ===`);
console.log(`  PASS: ${pass}`);
console.log(`  FAIL: ${fail}`);
if (warnings.length) console.log(`  WARN: ${warnings.length}`);
console.log('');

process.exit(fail > 0 ? 1 : 0);
