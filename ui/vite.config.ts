import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

const manifest = JSON.parse(
  readFileSync(new URL('../app.json', import.meta.url), 'utf8'),
) as { version: string }

export default defineConfig({
  plugins: [react()],
  define: {
    __LENS_BUILD__: JSON.stringify(manifest.version),
  },
  build: {
    lib: {
      entry: 'src/App.tsx',
      formats: ['es'],
      fileName: () => 'index.mjs',
    },
    outDir: 'dist',
    rollupOptions: {
      external: [
        'react', 'react-dom', 'react/jsx-runtime',
        '@kirocrew/app-sdk', '@kirocrew/app-sdk/ui', 'lucide-react',
      ],
    },
  },
})
