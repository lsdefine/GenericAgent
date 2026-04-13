import type { MovementState, SkinManifest, SkinAnimationConfig } from '@/types'

export function resolveAnimation(
  state: MovementState,
  manifest: SkinManifest,
): { state: MovementState; config: SkinAnimationConfig } | null {
  if (manifest.animations[state]) {
    return { state, config: manifest.animations[state]! }
  }

  const visited = new Set<MovementState>([state])
  let fallback = manifest.fallback?.[state]
  while (fallback && !visited.has(fallback)) {
    visited.add(fallback)
    if (manifest.animations[fallback]) {
      return { state: fallback, config: manifest.animations[fallback]! }
    }
    fallback = manifest.fallback?.[fallback]
  }

  if (manifest.animations.idle) {
    return { state: 'idle', config: manifest.animations.idle! }
  }

  return null
}
