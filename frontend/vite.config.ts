import { rmSync } from 'node:fs';
import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vitest/config';

const FIXTURE_DIR = 'jarvis/fixtures';

const dropJarvisFixtures = (): Plugin => {
  let outDir = 'dist';
  return {
    name: 'aios-drop-jarvis-fixtures',
    apply: 'build',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      rmSync(resolve(outDir, FIXTURE_DIR), { recursive: true, force: true });
    }
  };
};

const MODULES_DIR = resolve(__dirname, 'node_modules');

const resolveOutsideRoot = (): Plugin => ({
  name: 'aios-resolve-outside-root',
  enforce: 'pre',
  async resolveId(source, importer, options) {
    if (importer === undefined || /^[./]/.test(source) || source.startsWith('@/') || source.startsWith('@tests/') || source.startsWith('@support/')) {
      return null;
    }
    if (!importer.replaceAll('\\', '/').includes('/tests/')) {
      return null;
    }
    return this.resolve(source, resolve(MODULES_DIR, '_.js'), {
      ...options,
      skipSelf: true
    });
  }
});

export default defineConfig({
  plugins: [react(), dropJarvisFixtures(), resolveOutsideRoot()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@tests': resolve(__dirname, '..', 'tests', 'frontend'),
      '@support': resolve(__dirname, '..', 'tests', 'support', 'frontend')
    }
  },
  server: {
    fs: {
      allow: [resolve(__dirname, '..')]
    },
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8010',
        changeOrigin: true
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-dom/client']
        }
      }
    }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['../tests/frontend/**/*.test.{ts,tsx}', '../tests/architecture/frontend/**/*.test.{ts,tsx}'],
    setupFiles: ['../tests/frontend/setup.ts'],
    testTimeout: 15000,
    coverage: {
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/entities/**/types.ts',
        'src/app/main.tsx',
        'src/**/index.ts',
        '**/*.css',
        '**/.impeccable/**'
      ]
    }
  }
});
