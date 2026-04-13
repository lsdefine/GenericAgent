import { defineConfig } from 'astro/config'
import sitemap from '@astrojs/sitemap'

export default defineConfig({
  site: 'https://aibubu.app',
  i18n: {
    defaultLocale: 'zh',
    locales: ['zh', 'en'],
    routing: { prefixDefaultLocale: true },
  },
  integrations: [
    sitemap({
      filter: (page) => page !== 'https://aibubu.app/',
      i18n: {
        defaultLocale: 'zh',
        locales: { zh: 'zh', en: 'en' },
      },
    }),
  ],
  build: {
    inlineStylesheets: 'always',
  },
})
