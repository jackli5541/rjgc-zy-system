import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers'

// 生产构建时设置 VITE_CDN_BASE（以 / 结尾，如 OSS 的 lab/ 目录），静态资源将从该地址加载；不设置则仍由后端托管
export default defineConfig({
  base: process.env.VITE_CDN_BASE || '/',
  plugins: [
    vue(),
    Components({ resolvers: [AntDesignVueResolver({ importStyle: 'css-in-js' })] })
  ],
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
          vue: ['vue']
        }
      }
    }
  }
})
