/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OPS_API_URL?: string;
  readonly VITE_RUNTIME_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
