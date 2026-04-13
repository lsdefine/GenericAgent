#!/usr/bin/env node

/**
 * Synchronize version across:
 *   - packages/app/package.json
 *   - packages/app/src-tauri/Cargo.toml
 *   - packages/app/src-tauri/tauri.conf.json
 *
 * Usage:
 *   node scripts/bump-version.js 0.2.0
 *   node scripts/bump-version.js patch    (0.1.0 → 0.1.1)
 *   node scripts/bump-version.js minor    (0.1.0 → 0.2.0)
 *   node scripts/bump-version.js major    (0.1.0 → 1.0.0)
 */

import { readFileSync, writeFileSync } from 'fs'
import { resolve } from 'path'

const ROOT = resolve(import.meta.dirname, '..')
const APP_PKG = resolve(ROOT, 'packages/app/package.json')
const TAURI_CONF = resolve(ROOT, 'packages/app/src-tauri/tauri.conf.json')
const CARGO_TOML = resolve(ROOT, 'packages/app/src-tauri/Cargo.toml')

function readJSON(path) {
  return JSON.parse(readFileSync(path, 'utf-8'))
}

function writeJSON(path, data) {
  writeFileSync(path, JSON.stringify(data, null, 2) + '\n')
}

function bumpSemver(current, type) {
  const [major, minor, patch] = current.split('.').map(Number)
  switch (type) {
    case 'major':
      return `${major + 1}.0.0`
    case 'minor':
      return `${major}.${minor + 1}.0`
    case 'patch':
      return `${major}.${minor}.${patch + 1}`
    default:
      throw new Error(`Unknown bump type: ${type}`)
  }
}

const arg = process.argv[2]
if (!arg) {
  console.error('Usage: node scripts/bump-version.js <version|patch|minor|major>')
  process.exit(1)
}

const appPkg = readJSON(APP_PKG)
const currentVersion = appPkg.version

let newVersion
if (['patch', 'minor', 'major'].includes(arg)) {
  newVersion = bumpSemver(currentVersion, arg)
} else if (/^\d+\.\d+\.\d+$/.test(arg)) {
  newVersion = arg
} else {
  console.error(`Invalid version: "${arg}". Use semver (e.g. 0.2.0) or patch/minor/major.`)
  process.exit(1)
}

console.log(`Bumping version: ${currentVersion} → ${newVersion}\n`)

appPkg.version = newVersion
writeJSON(APP_PKG, appPkg)
console.log(`  ✓ packages/app/package.json`)

const tauriConf = readJSON(TAURI_CONF)
tauriConf.version = newVersion
writeJSON(TAURI_CONF, tauriConf)
console.log(`  ✓ packages/app/src-tauri/tauri.conf.json`)

let cargoContent = readFileSync(CARGO_TOML, 'utf-8')
cargoContent = cargoContent.replace(
  /^version\s*=\s*"[^"]*"/m,
  `version = "${newVersion}"`,
)
writeFileSync(CARGO_TOML, cargoContent)
console.log(`  ✓ packages/app/src-tauri/Cargo.toml`)

console.log(`\nDone! Version is now ${newVersion}`)
console.log(`\nNext steps:`)
console.log(`  1. Update CHANGELOG.md (or run: git-cliff -o CHANGELOG.md)`)
console.log(`  2. git add -A && git commit -m "chore(app): release v${newVersion}"`)
console.log(`  3. git tag v${newVersion}`)
console.log(`  4. git push origin main --tags`)
