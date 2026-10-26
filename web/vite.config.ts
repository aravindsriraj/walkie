import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The app talks to its own origin. In development, Vite forwards API paths to the Walkie server
// (WALKIE_API, default http://127.0.0.1:8000), so dev and the built app behave the same.
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {}
const api = env.WALKIE_API ?? 'http://127.0.0.1:8000'
const paths = ['/recordings', '/uploads', '/articles', '/files', '/a/', '/voices', '/languages', '/settings', '/my-voice']

export default defineConfig({
  plugins: [react()],
  server: { proxy: Object.fromEntries(paths.map((p) => [p, { target: api, changeOrigin: true }])) },
})
