import { describe, it, expect } from 'vitest'
import { resolveAnimation } from './skin'
import type { SkinManifest, SkinAnimationConfig } from '@/types'

function makeManifest(overrides: Partial<SkinManifest> = {}): SkinManifest {
  return {
    id: 'test',
    name: 'Test',
    version: '1.0.0',
    author: 'tester',
    description: '',
    style: 'pixel',
    format: 'sprite',
    size: { width: 48, height: 48 },
    animations: {},
    ...overrides,
  }
}

const idleAnim: SkinAnimationConfig = { file: 'idle.png', loop: true }
const walkAnim: SkinAnimationConfig = { file: 'walk.png', loop: true }
const runAnim: SkinAnimationConfig = { file: 'run.png', loop: true }
const sprintAnim: SkinAnimationConfig = { file: 'sprint.png', loop: true }

describe('resolveAnimation', () => {
  it('returns direct match when state has animation', () => {
    const manifest = makeManifest({ animations: { idle: idleAnim, walk: walkAnim } })
    const result = resolveAnimation('walk', manifest)
    expect(result).toEqual({ state: 'walk', config: walkAnim })
  })

  it('follows single-level fallback', () => {
    const manifest = makeManifest({
      animations: { idle: idleAnim, walk: walkAnim },
      fallback: { run: 'walk' },
    })
    const result = resolveAnimation('run', manifest)
    expect(result).toEqual({ state: 'walk', config: walkAnim })
  })

  it('follows multi-level fallback chain', () => {
    const manifest = makeManifest({
      animations: { idle: idleAnim, walk: walkAnim },
      fallback: { sprint: 'run', run: 'walk' },
    })
    const result = resolveAnimation('sprint', manifest)
    expect(result).toEqual({ state: 'walk', config: walkAnim })
  })

  it('falls back to idle when fallback chain leads nowhere', () => {
    const manifest = makeManifest({
      animations: { idle: idleAnim },
      fallback: { sprint: 'run' },
    })
    const result = resolveAnimation('sprint', manifest)
    expect(result).toEqual({ state: 'idle', config: idleAnim })
  })

  it('handles circular fallback without infinite loop', () => {
    const manifest = makeManifest({
      animations: { idle: idleAnim },
      fallback: { run: 'sprint', sprint: 'run' },
    })
    const result = resolveAnimation('run', manifest)
    expect(result).toEqual({ state: 'idle', config: idleAnim })
  })

  it('returns null when no animations at all', () => {
    const manifest = makeManifest({ animations: {} })
    const result = resolveAnimation('idle', manifest)
    expect(result).toBeNull()
  })

  it('falls back to idle when requested state missing and no fallback defined', () => {
    const manifest = makeManifest({ animations: { idle: idleAnim } })
    const result = resolveAnimation('sprint', manifest)
    expect(result).toEqual({ state: 'idle', config: idleAnim })
  })

  it('returns null when no fallback and no idle', () => {
    const manifest = makeManifest({ animations: { walk: walkAnim } })
    const result = resolveAnimation('sprint', manifest)
    expect(result).toBeNull()
  })

  it('prefers direct match over fallback', () => {
    const manifest = makeManifest({
      animations: { idle: idleAnim, run: runAnim, walk: walkAnim },
      fallback: { run: 'walk' },
    })
    const result = resolveAnimation('run', manifest)
    expect(result).toEqual({ state: 'run', config: runAnim })
  })

  it('handles all four states with direct animations', () => {
    const manifest = makeManifest({
      animations: { idle: idleAnim, walk: walkAnim, run: runAnim, sprint: sprintAnim },
    })
    expect(resolveAnimation('idle', manifest)?.state).toBe('idle')
    expect(resolveAnimation('walk', manifest)?.state).toBe('walk')
    expect(resolveAnimation('run', manifest)?.state).toBe('run')
    expect(resolveAnimation('sprint', manifest)?.state).toBe('sprint')
  })

  it('handles manifest without fallback field', () => {
    const manifest = makeManifest({ animations: { idle: idleAnim } })
    delete manifest.fallback
    const result = resolveAnimation('run', manifest)
    expect(result).toEqual({ state: 'idle', config: idleAnim })
  })
})
