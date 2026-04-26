/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_CLOUDINARY_CLOUD_NAME?: string
  readonly VITE_CLOUDINARY_UPLOAD_PRESET?: string
  readonly VITE_CLOUDINARY_SIGNED_PRESET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
