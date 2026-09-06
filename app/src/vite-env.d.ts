/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BANNER_AD_GROUP_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
