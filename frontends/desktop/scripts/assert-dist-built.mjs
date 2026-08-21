#!/usr/bin/env node
/**
 * assert-dist-built.mjs — Build artifact integrity check.
 *
 * Verifies that `vite build` produced a usable renderer payload.
 * Inspired by Hermes Desktop's `scripts/assert-dist-built.test.cjs`.
 *
 * Usage:
 *   node scripts/assert-dist-built.mjs [dist-dir]
 *
 * Exit codes:
 *   0 = all checks pass
 *   1 = one or more checks failed
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DESKTOP_ROOT = path.resolve(__dirname, '..');
const DEFAULT_DIST = path.resolve(__dirname, '..', 'dist');
const CHUNK_WARN_SIZE = 2 * 1024 * 1024; // 2 MB

/**
 * @param {string} distDir
 * @returns {{ ok: boolean, error?: string, warnings?: string[] }}
 */
export function checkDistBuilt(distDir) {
  const warnings = [];

  // React v2 public assets are an independent packaging boundary. The upstream static v1 tree is
  // deliberately not read here; its zero-diff invariant is enforced against the PR base in CI.
  for (const publicAsset of ['fallback.html', 'i18n.js', 'styles.css']) {
    const sourcePath = path.join(DESKTOP_ROOT, 'public', publicAsset);
    if (!fs.existsSync(sourcePath) || fs.statSync(sourcePath).size === 0) {
      return { ok: false, error: `public/${publicAsset} is missing or empty` };
    }
  }

  // 1. dist/ exists
  if (!fs.existsSync(distDir)) {
    return { ok: false, error: `no dist directory at ${distDir}` };
  }

  // 2. index.html exists and non-empty
  const indexPath = path.join(distDir, 'index.html');
  if (!fs.existsSync(indexPath)) {
    return { ok: false, error: 'index.html is missing from dist/' };
  }
  const indexContent = fs.readFileSync(indexPath, 'utf8');
  if (indexContent.trim().length === 0) {
    return { ok: false, error: 'index.html is empty' };
  }

  // 3. loading.html exists (Tauri cold-start splash)
  const loadingPath = path.join(distDir, 'loading.html');
  if (!fs.existsSync(loadingPath)) {
    return { ok: false, error: 'loading.html is missing from dist/ (required for Tauri cold start)' };
  }

  const fallbackPath = path.join(distDir, 'fallback.html');
  if (!fs.existsSync(fallbackPath)) {
    return { ok: false, error: 'fallback.html is missing from dist/ (required for bootstrap recovery)' };
  }

  // 4. assets/ contains at least one JS bundle
  const assetsDir = path.join(distDir, 'assets');
  if (!fs.existsSync(assetsDir)) {
    return { ok: false, error: 'assets/ directory is missing from dist/' };
  }
  const assetFiles = fs.readdirSync(assetsDir);
  const jsFiles = assetFiles.filter((f) => f.endsWith('.js'));
  if (jsFiles.length === 0) {
    return { ok: false, error: 'no built JS bundle found in dist/assets/' };
  }

  // 5. No oversized chunks
  for (const jsFile of jsFiles) {
    const size = fs.statSync(path.join(assetsDir, jsFile)).size;
    if (size > CHUNK_WARN_SIZE) {
      warnings.push(`chunk ${jsFile} is ${(size / 1024 / 1024).toFixed(1)}MB (> 2MB threshold)`);
    }
  }

  // 6. CSS files exist (app has styles)
  const cssFiles = assetFiles.filter((f) => f.endsWith('.css'));
  if (cssFiles.length === 0) {
    warnings.push('no CSS files in dist/assets/ — UI may appear unstyled');
  }

  const result = { ok: true };
  if (warnings.length > 0) result.warnings = warnings;
  return result;
}

// CLI entrypoint
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  const distDir = process.argv[2] || DEFAULT_DIST;
  console.log(`\n  Checking dist: ${distDir}\n`);

  const result = checkDistBuilt(distDir);

  if (!result.ok) {
    console.error(`  ✗ FAIL: ${result.error}\n`);
    process.exit(1);
  }

  if (result.warnings?.length) {
    for (const w of result.warnings) {
      console.warn(`  ⚠ WARNING: ${w}`);
    }
    console.log('');
  }

  const assetsDir = path.join(distDir, 'assets');
  const assetFiles = fs.readdirSync(assetsDir);
  const jsFiles = assetFiles.filter((f) => f.endsWith('.js'));
  const cssFiles = assetFiles.filter((f) => f.endsWith('.css'));
  const totalSize = assetFiles.reduce((sum, f) => sum + fs.statSync(path.join(assetsDir, f)).size, 0);

  console.log(`  ✓ dist/index.html present`);
  console.log(`  ✓ dist/loading.html present`);
  console.log(`  ✓ React v2 public recovery assets and dist/fallback.html are present`);
  console.log(`  ✓ ${jsFiles.length} JS bundle(s), ${cssFiles.length} CSS file(s)`);
  console.log(`  ✓ Total assets size: ${(totalSize / 1024).toFixed(0)} KB`);
  console.log(`\n  PASS\n`);
  process.exit(0);
}
