import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  root: '.',
  publicDir: 'public',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: true,
    minify: 'terser',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
      },
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      // Proxy all API requests to backend
      '/tasks': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/repos': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/blocked': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/config': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/context': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/interject': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
      '/stop': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/kill': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/estop': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/pending': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/token_usage': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/orchestrator': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      // Status API endpoint - needed for app.ts initial data load
      '/status': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  // Handle SPA fallback for direct navigation
  appType: 'spa',
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.ts'],
  },
});
