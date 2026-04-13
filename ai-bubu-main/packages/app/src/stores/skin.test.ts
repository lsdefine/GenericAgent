import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSkinStore } from './skin'
import type { SkinManifest } from '@/types'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'

const mockedInvoke = vi.mocked(invoke)

function makeFetchResponse(body: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 404,
    json: () => Promise.resolve(body),
  } as Response
}

function makeManifest(id: string): SkinManifest {
  return {
    id,
    name: id.charAt(0).toUpperCase() + id.slice(1),
    version: '1.0.0',
    author: 'test',
    description: '',
    style: 'pixel',
    format: 'sprite',
    size: { width: 48, height: 48 },
    animations: {
      idle: { file: 'idle.png', loop: true },
    },
  }
}

describe('useSkinStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeFetchResponse(makeManifest('vita')))
  })

  it('initializes with vita defaults', () => {
    const store = useSkinStore()
    expect(store.currentManifest.id).toBe('vita')
    expect(store.catalogLoaded).toBe(false)
    expect(store.catalog).toEqual([])
  })

  it('skinBasePath reflects current skin id', () => {
    const store = useSkinStore()
    expect(store.skinBasePath).toBe('/skins/vita/')
  })

  describe('loadCatalog', () => {
    it('loads skins from invoke list_skins and fetches manifests', async () => {
      mockedInvoke.mockResolvedValue([
        { id: 'vita', builtin: true },
        { id: 'doux', builtin: true },
        { id: 'custom', builtin: false },
      ])

      const vitaManifest = makeManifest('vita')
      const douxManifest = makeManifest('doux')
      const customManifest = makeManifest('custom')

      vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
        const urlStr = String(url)
        if (urlStr.includes('/vita/')) return Promise.resolve(makeFetchResponse(vitaManifest))
        if (urlStr.includes('/doux/')) return Promise.resolve(makeFetchResponse(douxManifest))
        if (urlStr.includes('/custom/')) return Promise.resolve(makeFetchResponse(customManifest))
        return Promise.resolve(makeFetchResponse(null, false))
      })

      const store = useSkinStore()
      await store.loadCatalog()

      expect(mockedInvoke).toHaveBeenCalledWith('list_skins')
      expect(store.catalogLoaded).toBe(true)
      expect(store.catalog).toHaveLength(3)
      expect(store.catalog.map((e) => e.id)).toEqual(['vita', 'doux', 'custom'])
    })

    it('sets builtinSkinIds from list_skins response', async () => {
      mockedInvoke.mockResolvedValue([
        { id: 'vita', builtin: true },
        { id: 'custom', builtin: false },
      ])

      vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
        const urlStr = String(url)
        if (urlStr.includes('/vita/'))
          return Promise.resolve(makeFetchResponse(makeManifest('vita')))
        if (urlStr.includes('/custom/'))
          return Promise.resolve(makeFetchResponse(makeManifest('custom')))
        return Promise.resolve(makeFetchResponse(null, false))
      })

      const store = useSkinStore()
      await store.loadCatalog()

      expect(store.isBuiltin('vita')).toBe(true)
      expect(store.isBuiltin('custom')).toBe(false)
      expect(store.isBuiltin('nonexistent')).toBe(false)
    })

    it('skips skins whose skin.json fetch fails', async () => {
      mockedInvoke.mockResolvedValue([
        { id: 'vita', builtin: true },
        { id: 'broken', builtin: true },
      ])

      vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
        const urlStr = String(url)
        if (urlStr.includes('/vita/'))
          return Promise.resolve(makeFetchResponse(makeManifest('vita')))
        if (urlStr.includes('/broken/')) return Promise.resolve(makeFetchResponse(null, false))
        return Promise.resolve(makeFetchResponse(null, false))
      })

      const store = useSkinStore()
      await store.loadCatalog()

      expect(store.catalog).toHaveLength(1)
      expect(store.catalog[0].id).toBe('vita')
    })

    it('handles invoke failure gracefully', async () => {
      mockedInvoke.mockRejectedValue(new Error('Tauri not available'))

      const store = useSkinStore()
      await store.loadCatalog()

      expect(store.catalogLoaded).toBe(false)
      expect(store.catalog).toEqual([])
    })
  })

  describe('isBuiltin', () => {
    it('returns false for unknown skin id', () => {
      const store = useSkinStore()
      expect(store.isBuiltin('never-registered')).toBe(false)
    })
  })

  describe('getAnimationForState', () => {
    it('returns animation with full src path', () => {
      const store = useSkinStore()
      store.currentManifest = makeManifest('vita')

      const result = store.getAnimationForState('idle')
      expect(result).not.toBeNull()
      expect(result!.src).toBe('/skins/vita/idle.png')
      expect(result!.state).toBe('idle')
    })

    it('returns null when no matching animation', () => {
      const store = useSkinStore()
      store.currentManifest = { ...makeManifest('vita'), animations: {} }

      const result = store.getAnimationForState('sprint')
      expect(result).toBeNull()
    })
  })

  describe('removeSkin', () => {
    it('rejects removing builtin skin', async () => {
      mockedInvoke.mockResolvedValueOnce([{ id: 'vita', builtin: true }])
      vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
        const urlStr = String(url)
        if (urlStr.includes('/vita/'))
          return Promise.resolve(makeFetchResponse(makeManifest('vita')))
        return Promise.resolve(makeFetchResponse(null, false))
      })

      const store = useSkinStore()
      await store.loadCatalog()

      const result = await store.removeSkin('vita')
      expect(result.success).toBe(false)
    })

    it('calls invoke remove_skin for non-builtin skin', async () => {
      mockedInvoke.mockResolvedValueOnce([
        { id: 'vita', builtin: true },
        { id: 'custom', builtin: false },
      ])
      vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
        const urlStr = String(url)
        if (urlStr.includes('/vita/'))
          return Promise.resolve(makeFetchResponse(makeManifest('vita')))
        if (urlStr.includes('/custom/'))
          return Promise.resolve(makeFetchResponse(makeManifest('custom')))
        return Promise.resolve(makeFetchResponse(null, false))
      })

      const store = useSkinStore()
      await store.loadCatalog()

      mockedInvoke.mockResolvedValueOnce({
        success: true,
        skin_id: 'custom',
        message: '已移除角色: custom',
      })

      const result = await store.removeSkin('custom')
      expect(result.success).toBe(true)
      expect(store.catalog.find((e) => e.id === 'custom')).toBeUndefined()
    })

    it('handles invoke error in removeSkin', async () => {
      mockedInvoke.mockResolvedValueOnce([{ id: 'custom', builtin: false }])
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeFetchResponse(makeManifest('custom')))

      const store = useSkinStore()
      await store.loadCatalog()

      mockedInvoke.mockRejectedValueOnce(new Error('disk error'))

      const result = await store.removeSkin('custom')
      expect(result.success).toBe(false)
      expect(result.message).toContain('disk error')
    })
  })
})
