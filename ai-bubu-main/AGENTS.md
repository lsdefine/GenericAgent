# AI 步步 (AIbubu) — Agent Instructions

## Project

AIbubu is a Tauri 2 desktop pet app that monitors AI coding tool activity and visualizes it as step counts driving a pixel-art pet.

## Architecture

- **Monorepo**: pnpm workspace with `packages/app` (Tauri desktop app) and `packages/site` (Astro marketing site)
- **Frontend**: Vue 3 + Pinia + Vite 6
- **Backend**: Rust (Tauri 2)
- **Testing**: Vitest + happy-dom

## Key Paths

| Path                          | Description                    |
| ----------------------------- | ------------------------------ |
| `packages/app/src/`           | Vue 3 frontend source          |
| `packages/app/src-tauri/src/` | Rust backend source            |
| `packages/app/providers/`     | AI tool monitor configs (TOML) |
| `packages/app/public/skins/`  | Skin assets                    |
| `packages/site/src/`          | Astro site source              |
| `scripts/`                    | Utility scripts                |

## Commands

```bash
pnpm dev              # Frontend dev server (used by Tauri beforeDevCommand)
pnpm tauri dev        # Full Tauri dev mode
pnpm dev:mock         # Tauri dev mode with mock peer data
pnpm test             # Run tests
pnpm lint             # ESLint
pnpm format           # Prettier
pnpm validate:skins   # Validate skin assets
pnpm dev:site         # Site dev server
pnpm bump <level>     # Bump version (patch/minor/major)
```

## Commit Convention

Conventional Commits enforced by commitlint + Husky.

Format: `type(scope): description`

Allowed scopes: `app`, `site`, `skin`, `monitor`, `social`, `i18n`, `ci`, `deps`

Use the **panda-git-commit** skill for generating commit messages.

## Coding Standards

- TypeScript: use `import type` for type-only imports
- Vue: PascalCase components, `use` prefix for composables
- Rust: must pass `cargo fmt` and `cargo clippy -- -D warnings`
- No `console.log` — use `console.warn` / `console.error`
- Path alias: `@/` → `packages/app/src/`

## Skin System

Each skin directory under `packages/app/public/skins/` must contain:

- `skin.json` with fields: `name`, `author`, `animations` (at least `idle`)
- `pet.png` sprite sheet

Skins are auto-discovered from directories containing `skin.json`. No manual registration needed.

Run `pnpm validate:skins` after any skin changes.

## Version Management

Version synced across 3 files — use `pnpm bump`:

1. `packages/app/package.json`
2. `packages/app/src-tauri/Cargo.toml`
3. `packages/app/src-tauri/tauri.conf.json`

## Constraints

- LAN social: UDP broadcast on port 23456
- macOS minimum: 14.0
- Do not modify `.husky/` hooks unless explicitly asked
- CSP policy in `tauri.conf.json` — update when adding external resources
