#!/usr/bin/env node

/**
 * Provider TOML validator — runs in pre-commit to ensure:
 *   1. Every .toml file in providers/ parses correctly
 *   2. Required fields exist (meta.id, meta.name, detect.adapter, activity.adapter)
 *   3. Adapter-specific config blocks match the declared adapter type
 */

import { readdirSync, readFileSync } from 'fs'
import { join, resolve } from 'path'
import { parse } from 'smol-toml'

const PROVIDERS_DIR = resolve(import.meta.dirname, '..', 'packages', 'app', 'providers')

const VALID_ADAPTERS = ['sqlite', 'jsonl', 'process', 'file_mtime', 'vscode_ext']
const VALID_CATEGORIES = ['ide', 'cli', 'extension']

const ADAPTER_REQUIRED_BLOCKS = {
  sqlite: 'sqlite',
  jsonl: 'jsonl',
  file_mtime: 'file_mtime',
  process: 'process',
}

let errors = 0
let warnings = 0

function fail(file, msg) {
  console.error(`  ✗ ${file}: ${msg}`)
  errors++
}

function warn(file, msg) {
  console.warn(`  ⚠ ${file}: ${msg}`)
  warnings++
}

function info(msg) {
  console.log(`  ✓ ${msg}`)
}

console.log('Validating providers...\n')

const tomlFiles = readdirSync(PROVIDERS_DIR).filter((f) => f.endsWith('.toml'))

info(`Found ${tomlFiles.length} provider files`)

for (const file of tomlFiles) {
  const filePath = join(PROVIDERS_DIR, file)
  let content
  try {
    content = readFileSync(filePath, 'utf-8')
  } catch {
    fail(file, 'cannot read file')
    continue
  }

  let config
  try {
    config = parse(content)
  } catch (e) {
    fail(file, `TOML parse error: ${e.message}`)
    continue
  }

  if (!config.meta) {
    fail(file, 'missing [meta] section')
    continue
  }

  if (!config.meta.id) fail(file, 'missing meta.id')
  if (!config.meta.name) fail(file, 'missing meta.name')
  if (!config.meta.category) {
    fail(file, 'missing meta.category')
  } else if (!VALID_CATEGORIES.includes(config.meta.category)) {
    fail(file, `invalid meta.category "${config.meta.category}" (expected: ${VALID_CATEGORIES.join(', ')})`)
  }

  if (!config.detect) {
    fail(file, 'missing [detect] section')
    continue
  }
  if (!config.detect.adapter) {
    fail(file, 'missing detect.adapter')
  } else if (!VALID_ADAPTERS.includes(config.detect.adapter)) {
    fail(file, `invalid detect.adapter "${config.detect.adapter}" (expected: ${VALID_ADAPTERS.join(', ')})`)
  }

  const needsPaths = ['sqlite', 'jsonl', 'file_mtime', 'vscode_ext']
  if (needsPaths.includes(config.detect.adapter) && !config.detect.paths) {
    fail(file, `adapter "${config.detect.adapter}" requires [detect.paths]`)
  }

  if (!config.activity) {
    fail(file, 'missing [activity] section')
    continue
  }
  if (!config.activity.adapter) {
    fail(file, 'missing activity.adapter')
  } else if (!VALID_ADAPTERS.includes(config.activity.adapter)) {
    fail(file, `invalid activity.adapter "${config.activity.adapter}" (expected: ${VALID_ADAPTERS.join(', ')})`)
  }

  const activityAdapter = config.activity.adapter
  const requiredBlock = ADAPTER_REQUIRED_BLOCKS[activityAdapter]
  if (requiredBlock && !config.activity[requiredBlock]) {
    fail(file, `activity.adapter="${activityAdapter}" requires [activity.${requiredBlock}] block`)
  }

  if (activityAdapter === 'sqlite') {
    const sq = config.activity.sqlite
    if (sq) {
      if (!sq.latest_query) fail(file, 'activity.sqlite missing latest_query')
      if (!sq.timestamp_field) fail(file, 'activity.sqlite missing timestamp_field')
    }
  }

  if (activityAdapter === 'jsonl') {
    const jl = config.activity.jsonl
    if (jl) {
      if (!jl.file_pattern) fail(file, 'activity.jsonl missing file_pattern')
      if (!jl.timestamp_field) fail(file, 'activity.jsonl missing timestamp_field')
    }
  }

  if (activityAdapter === 'process') {
    const pr = config.activity.process
    if (pr) {
      if (!pr.names || pr.names.length === 0) fail(file, 'activity.process missing names')
    }
  }

  if (activityAdapter === 'file_mtime') {
    const fm = config.activity.file_mtime
    if (fm) {
      if (!fm.watch_pattern) fail(file, 'activity.file_mtime missing watch_pattern')
    }
  }

  if (activityAdapter === 'vscode_ext' && !config.variants) {
    fail(file, 'adapter "vscode_ext" requires [[variants]] entries')
  }

  info(`${file}: adapter=${activityAdapter}, category=${config.meta.category}`)
}

console.log('')
if (errors > 0) {
  console.error(`Found ${errors} error(s), ${warnings} warning(s). Please fix before committing.`)
  process.exit(1)
} else if (warnings > 0) {
  console.log(`All providers valid. ${warnings} warning(s).`)
} else {
  console.log('All providers valid.')
}
