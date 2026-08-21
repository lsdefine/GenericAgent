import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(desktopRoot, '..', '..');
const failures = [];

function readText(relativePath, base = desktopRoot) {
  return fs.readFileSync(path.join(base, relativePath), 'utf8');
}

function readJson(relativePath, base = desktopRoot) {
  return JSON.parse(readText(relativePath, base));
}

function check(condition, message) {
  if (condition) {
    console.log(`  ✓ ${message}`);
  } else {
    failures.push(message);
    console.error(`  ✗ ${message}`);
  }
}

function compareDependencySets(label, manifestValues = {}, lockValues = {}) {
  const manifestKeys = Object.keys(manifestValues).sort();
  const lockKeys = Object.keys(lockValues).sort();
  check(
    JSON.stringify(manifestKeys) === JSON.stringify(lockKeys),
    `${label} keys match package-lock.json`,
  );

  for (const name of manifestKeys) {
    check(
      manifestValues[name] === lockValues[name],
      `${label}.${name} version matches package-lock.json`,
    );
  }
}

console.log('[1] npm manifest and lockfile');
const packageJson = readJson('package.json');
const packageLock = readJson('package-lock.json');
const lockRoot = packageLock.packages?.[''];
check(Boolean(lockRoot), 'package-lock.json has a root package entry');
if (lockRoot) {
  check(packageJson.name === lockRoot.name, 'package name matches package-lock.json');
  check(packageJson.version === lockRoot.version, 'package version matches package-lock.json');
  compareDependencySets('dependencies', packageJson.dependencies, lockRoot.dependencies);
  compareDependencySets('devDependencies', packageJson.devDependencies, lockRoot.devDependencies);
}

const requiredScripts = [
  'build',
  'typecheck',
  'test',
  'test:ci-contract',
  'test:e2e-isolation',
  'test:e2e-types',
  'test:packaging',
  'e2e:browser',
  'e2e:desktop',
  'e2e:desktop:full',
  'e2e:canary',
  'tauri',
];
for (const name of requiredScripts) {
  check(Boolean(packageJson.scripts?.[name]), `npm script exists: ${name}`);
}

const gitignore = readText('.gitignore');
check(!/^package-lock\.json\s*$/m.test(gitignore), 'package-lock.json is not ignored');

console.log('\n[2] workflow command contract');
const workflowPaths = [
  '.github/workflows/desktop-ci.yml',
  '.github/workflows/desktop-release-package.yml',
];
for (const workflowPath of workflowPaths) {
  const workflow = readText(workflowPath, repoRoot);
  const referencedScripts = [...workflow.matchAll(/npm run ([a-zA-Z0-9:_-]+)/g)].map(
    (match) => match[1],
  );
  for (const name of new Set(referencedScripts)) {
    check(Boolean(packageJson.scripts?.[name]), `${workflowPath} references npm script: ${name}`);
  }
  check(
    !/\bnpx\s+(?:tsc|tsx|vite|vitest|wdio)\b/.test(workflow),
    `${workflowPath} does not use npx fallback for pinned tools`,
  );
}

const releaseWorkflow = readText('.github/workflows/desktop-release-package.yml', repoRoot);
for (const job of ['build-windows', 'build-linux', 'build-macos']) {
  check(new RegExp(`^  ${job}:\\s*$`, 'm').test(releaseWorkflow), `release workflow keeps upstream job: ${job}`);
}
check(
  !/\b(?:aiortc|cryptography)\b/.test(releaseWorkflow),
  'portable packages do not add optional heavy P2P dependencies',
);
check(
  !fs.existsSync(path.join(repoRoot, '.github/workflows/desktop-e2e-nightly.yml')),
  'fork-only nightly workflow is absent',
);

console.log('\n[3] Tauri and native E2E contract');
const cargoToml = readText('src-tauri/Cargo.toml');
check(/^\[features\]$/m.test(cargoToml), 'Cargo.toml declares a features section');
check(/^e2e\s*=\s*\[/m.test(cargoToml), 'Cargo.toml declares the e2e feature');
check(cargoToml.includes('tauri-plugin-wdio'), 'Cargo.toml declares WDIO plugins');

const requiredFiles = [
  'e2e/run.ts',
  'e2e/wdio.browser.conf.ts',
  'e2e/wdio.desktop.conf.ts',
  'e2e/package/real_package_journey.py',
  'e2e/package/verify_candidate_evidence.py',
  'e2e/windows/Invoke-WindowsUserJourney.ps1',
  'e2e/linux/Invoke-LinuxUserJourney.sh',
  'e2e/macos/Invoke-macOSUserJourney.sh',
  'src-tauri/tauri.e2e.conf.json',
  'tsconfig.e2e.json',
];
for (const relativePath of requiredFiles) {
  check(fs.existsSync(path.join(desktopRoot, relativePath)), `required E2E file exists: ${relativePath}`);
}

const tauriConfig = readJson('src-tauri/tauri.conf.json');
check(tauriConfig.build?.frontendDist === '../dist', 'Tauri packages the React dist directory');
check(tauriConfig.build?.beforeBuildCommand === 'npm run build', 'Tauri runs the frontend build first');
check(
  tauriConfig.app?.security?.capabilities?.includes('default'),
  'Tauri explicitly enables the default capability',
);

console.log('\n[4] bootstrap and window capability contract');
for (const relativePath of ['public/fallback.html', 'public/i18n.js', 'public/styles.css']) {
  const absolutePath = path.join(desktopRoot, relativePath);
  check(fs.existsSync(absolutePath) && fs.statSync(absolutePath).size > 0, `${relativePath} is present`);
}

const capability = readJson('src-tauri/capabilities/default.json');
const permissions = new Set(capability.permissions ?? []);
for (const permission of [
  'core:window:allow-minimize',
  'core:window:allow-toggle-maximize',
  'core:window:allow-close',
  'core:window:allow-start-dragging',
  'allow-retry-bootstrap',
  'allow-get-bootstrap-snapshot',
]) {
  check(permissions.has(permission), `capability grants: ${permission}`);
}

console.log('\n=== CI contract result ===');
if (failures.length > 0) {
  console.error(`FAIL: ${failures.length} contract violation(s)`);
  process.exitCode = 1;
} else {
  console.log('PASS: desktop CI inputs are internally consistent');
}
