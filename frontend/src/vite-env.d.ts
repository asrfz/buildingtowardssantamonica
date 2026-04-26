/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  /** Optional; same ObjectId as root .env DEFAULT_USER_ID if you want offline defaults without calling the API */
  readonly VITE_DEFAULT_USER_ID?: string
  readonly VITE_CLOUDINARY_CLOUD_NAME?: string
  readonly VITE_CLOUDINARY_UPLOAD_PRESET?: string
  readonly VITE_CLOUDINARY_SIGNED_PRESET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
