import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The public website (GitHub Pages): just the landing page. Relative paths, so it works under /walkie/.
export default defineConfig({
  root: 'site',
  base: './',
  plugins: [react()],
  build: { outDir: '../dist-site', emptyOutDir: true },
})
