#!/usr/bin/env node

/**
 * Skin consistency validator — runs in pre-commit to ensure:
 *   1. Every skin directory has skin.json with required fields
 *   2. Every animation references an existing file
 *   3. pet.png exists for each skin
 */

import { readdirSync, readFileSync, existsSync, statSync } from 'fs'
import { join, resolve } from 'path'

const SKINS_DIR = resolve(import.meta.dirname, '..', 'packages', 'app', 'public', 'skins')
const REQUIRED_FIELDS = ['name', 'author', 'animations']
const VALID_STATES = ['idle', 'walk', 'run', 'sprint']

let errors = 0

function fail(msg) {
  console.error(`  ✗ ${msg}`)
  errors++
}

function info(msg) {
  console.log(`  ✓ ${msg}`)
}

console.log('Validating skins...\n')

const skinDirs = readdirSync(SKINS_DIR)
  .filter((f) => statSync(join(SKINS_DIR, f)).isDirectory())
  .sort()

info(`发现 ${skinDirs.length} 个皮肤目录`)

for (const skinId of skinDirs) {
  const skinDir = join(SKINS_DIR, skinId)
  const skinJsonPath = join(skinDir, 'skin.json')
  const petPngPath = join(skinDir, 'pet.png')

  if (!existsSync(skinJsonPath)) {
    fail(`${skinId}: 缺少 skin.json`)
    continue
  }

  let manifest
  try {
    manifest = JSON.parse(readFileSync(skinJsonPath, 'utf-8'))
  } catch {
    fail(`${skinId}: skin.json 解析失败`)
    continue
  }

  for (const field of REQUIRED_FIELDS) {
    if (!manifest[field]) {
      fail(`${skinId}: skin.json 缺少必填字段 "${field}"`)
    }
  }

  if (!existsSync(petPngPath)) {
    fail(`${skinId}: 缺少 pet.png`)
  }

  if (manifest.animations) {
    const states = Object.keys(manifest.animations)
    for (const state of states) {
      if (!VALID_STATES.includes(state)) {
        fail(`${skinId}: 未知动画状态 "${state}"`)
      }
      const anim = manifest.animations[state]
      if (!anim.file) {
        fail(`${skinId}: 动画 "${state}" 缺少 file 字段`)
      } else if (!existsSync(join(skinDir, anim.file))) {
        fail(`${skinId}: 动画文件 "${anim.file}" 不存在`)
      }
      if (anim.sprite) {
        const spriteFields = ['frameWidth', 'frameHeight', 'frameCount', 'columns', 'fps']
        for (const sf of spriteFields) {
          if (anim.sprite[sf] == null) {
            fail(`${skinId}: 动画 "${state}" sprite 缺少 ${sf}`)
          }
        }
      }
    }

    if (!manifest.animations.idle) {
      fail(`${skinId}: 缺少必须的 idle 动画`)
    }

    info(`${skinId}: ${states.length} 个动画状态`)
  }
}

const orderPath = join(SKINS_DIR, 'order.json')
if (existsSync(orderPath)) {
  try {
    const order = JSON.parse(readFileSync(orderPath, 'utf-8'))
    if (!Array.isArray(order)) {
      fail('order.json 必须是字符串数组')
    } else {
      for (const id of order) {
        if (!skinDirs.includes(id)) {
          fail(`order.json 引用了不存在的皮肤目录: ${id}`)
        }
      }
      for (const id of skinDirs) {
        if (!order.includes(id)) {
          fail(`皮肤目录 ${id} 未在 order.json 中注册`)
        }
      }
      info(`order.json: ${order.length} 个皮肤，顺序一致`)
    }
  } catch {
    fail('order.json 解析失败')
  }
} else {
  fail('缺少 order.json 文件')
}

console.log('')
if (errors > 0) {
  console.error(`发现 ${errors} 个错误，请修复后再提交。`)
  process.exit(1)
} else {
  console.log('所有皮肤校验通过。')
}
