import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 8080,
    strictPort: true,
    host: '0.0.0.0',
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000'
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue'],
          antd: ['ant-design-vue', '@ant-design/icons-vue']
        }
      }
    }
  }
})
