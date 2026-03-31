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
      '/status': {
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
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.ts'],
  },
});
