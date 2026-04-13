import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import pluginAstro from 'eslint-plugin-astro'
import prettier from 'eslint-config-prettier'

export default [
  { ignores: ['**/dist/', '**/node_modules/', '**/target/', '**/*.d.ts'] },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  ...pluginAstro.configs.recommended,
  prettier,

  {
    files: ['packages/app/src/**/*.{ts,vue}'],
    languageOptions: {
      globals: {
        window: 'readonly',
        document: 'readonly',
        navigator: 'readonly',
        localStorage: 'readonly',
        sessionStorage: 'readonly',
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        fetch: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
        HTMLElement: 'readonly',
        HTMLImageElement: 'readonly',
        HTMLCanvasElement: 'readonly',
        Event: 'readonly',
        KeyboardEvent: 'readonly',
        MouseEvent: 'readonly',
        StorageEvent: 'readonly',
        MediaQueryListEvent: 'readonly',
        IntersectionObserver: 'readonly',
        MutationObserver: 'readonly',
        ResizeObserver: 'readonly',
        crypto: 'readonly',
        HTMLDivElement: 'readonly',
        Image: 'readonly',
        __APP_VERSION__: 'readonly',
      },
      parserOptions: {
        parser: tseslint.parser,
      },
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/html-self-closing': [
        'warn',
        { html: { void: 'always', normal: 'never', component: 'always' } },
      ],
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/consistent-type-imports': ['warn', { prefer: 'type-imports' }],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },

  {
    files: ['packages/site/src/**/*.{ts,js}'],
    languageOptions: {
      globals: {
        window: 'readonly',
        document: 'readonly',
        localStorage: 'readonly',
        console: 'readonly',
      },
    },
    rules: {
      'no-console': 'off',
    },
  },
]
