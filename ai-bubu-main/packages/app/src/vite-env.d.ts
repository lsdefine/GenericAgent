/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOCK_PEERS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare const __APP_VERSION__: string

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
