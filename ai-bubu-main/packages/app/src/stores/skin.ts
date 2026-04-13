import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { useSettingsStore } from './settings'
import { useI18n } from '@/composables/useI18n'
import type { SkinManifest, MovementState, SkinAnimationConfig } from '@/types'
import { resolveAnimation } from '@/utils/skin'

interface SkinEntry {
  id: string
  builtin: boolean
}

export interface CatalogEntry {
  id: string
  manifest: SkinManifest
}

export const useSkinStore = defineStore('skin', () => {
  const settings = useSettingsStore()
  const { t } = useI18n()

  let builtinSkinIds = new Set<string>()

  const catalog = ref<CatalogEntry[]>([])
  const catalogLoaded = ref(false)

  const currentManifest = ref<SkinManifest>({
    id: 'vita',
    name: 'Vita',
    version: '1.0.0',
    author: '',
    description: '',
    style: 'pixel',
    format: 'sprite',
    size: { width: 48, height: 48 },
    animations: {},
  })
  const skinBasePath = computed(() => `/skins/${currentManifest.value.id}/`)

  function getAnimationForState(state: MovementState): {
    state: MovementState
    config: SkinAnimationConfig
    src: string
  } | null {
    const result = resolveAnimation(state, currentManifest.value)
    if (!result) return null

    return {
      ...result,
      src: skinBasePath.value + result.config.file,
    }
  }

  let abortController: AbortController | null = null

  async function loadSkin(skinId: string) {
    if (abortController) {
      abortController.abort()
      abortController = null
    }

    abortController = new AbortController()

    try {
      const resp = await fetch(`/skins/${skinId}/skin.json`, {
        signal: abortController.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const manifest: SkinManifest = await resp.json()
      manifest.id = skinId
      currentManifest.value = manifest
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      console.error('Failed to load skin:', err)
    }
  }

  async function loadCatalog() {
    try {
      const skinEntries = await invoke<SkinEntry[]>('list_skins')

      builtinSkinIds = new Set(skinEntries.filter((e) => e.builtin).map((e) => e.id))

      const results = await Promise.allSettled(
        skinEntries.map(async ({ id }) => {
          const r = await fetch(`/skins/${id}/skin.json`)
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          const manifest: SkinManifest = await r.json()
          manifest.id = id
          return { id, manifest } as CatalogEntry
        }),
      )
      const entries = results
        .filter((r): r is PromiseFulfilledResult<CatalogEntry> => r.status === 'fulfilled')
        .map((r) => r.value)
      catalog.value = entries
      catalogLoaded.value = true

      if (entries.length > 0) {
        const validIds = entries.map((e) => e.id)
        if (!validIds.includes(settings.currentSkinId)) {
          settings.currentSkinId = entries[0].id
        }
      }
    } catch {
      /* catalog load failed, non-critical */
    }
  }

  function isBuiltin(skinId: string): boolean {
    return builtinSkinIds.has(skinId)
  }

  const manifestCache = new Map<string, SkinManifest>()

  async function getManifest(skinId: string): Promise<SkinManifest | null> {
    const catalogEntry = catalog.value.find((e) => e.id === skinId)
    if (catalogEntry) return catalogEntry.manifest

    const cached = manifestCache.get(skinId)
    if (cached) return cached

    try {
      const resp = await fetch(`/skins/${skinId}/skin.json`)
      if (!resp.ok) return null
      const manifest: SkinManifest = await resp.json()
      manifest.id = skinId
      manifestCache.set(skinId, manifest)
      return manifest
    } catch {
      return null
    }
  }

  async function removeSkin(skinId: string): Promise<{ success: boolean; message: string }> {
    if (isBuiltin(skinId)) {
      return { success: false, message: t('skinCannotRemove') }
    }

    try {
      const result = await invoke<{ success: boolean; skin_id: string; message: string }>(
        'remove_skin',
        { skinId },
      )

      if (result.success) {
        catalog.value = catalog.value.filter((e) => e.id !== skinId)

        if (settings.currentSkinId === skinId) {
          const fallback = catalog.value[0]?.id ?? 'vita'
          settings.currentSkinId = fallback
        }
      }

      return { success: result.success, message: result.message }
    } catch (err) {
      return { success: false, message: `${t('skinRemoveFail')}: ${err}` }
    }
  }

  watch(
    () => settings.currentSkinId,
    (id) => loadSkin(id),
    { immediate: true },
  )

  return {
    catalog,
    catalogLoaded,
    currentManifest,
    getAnimationForState,
    skinBasePath,
    loadSkin,
    loadCatalog,
    isBuiltin,
    getManifest,
    removeSkin,
  }
})
