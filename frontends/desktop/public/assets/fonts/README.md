# Desktop Font Assets

These font files are the offline Latin bundle for the vanilla desktop shell.

## Files

- `azonix-wordmark.woff2`
  - Role: brand wordmark only
  - Source: converted on 2026-05-25 from the local owner-installed file at `~/Library/Fonts/azonix/Azonix.otf`
  - License: owner-provided / verify before external redistribution
  - Note: this repo currently treats Azonix as a project-local brand asset

- `lexend-latin.woff2`
  - Role: English titles and navigation
  - Source: Google Fonts CSS2 API, specimen page <https://fonts.google.com/specimen/Lexend>
  - Downloaded: 2026-05-25
  - License: SIL Open Font License 1.1

- `noto-sans-latin.woff2`
  - Role: English body copy and default Latin UI text
  - Source: Google Fonts CSS2 API, specimen page <https://fonts.google.com/noto/specimen/Noto+Sans>
  - Downloaded: 2026-05-25
  - License: SIL Open Font License 1.1

- `jetbrains-mono-latin.woff2`
  - Role: config/value dense controls and numeric surfaces
  - Source: Google Fonts CSS2 API, specimen page <https://fonts.google.com/specimen/JetBrains+Mono>
  - Downloaded: 2026-05-25
  - License: SIL Open Font License 1.1

## Notes

- Only Latin subsets are bundled here. Chinese UI text continues to use the existing system fallback stack.
- Runtime does not fetch fonts from a CDN. `frontends/desktop/static/assets/fonts/fonts.css` is the only font entrypoint for the vanilla shell.
