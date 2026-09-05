import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import aitDevtools from '@apps-in-toss/devtools/unplugin'

// v3 웹뷰는 https://{appName}.web.tossmini.com 루트 서빙 → base는 절대경로 '/'
export default defineConfig({
  base: '/',
  plugins: [aitDevtools.vite(), react()],
})
