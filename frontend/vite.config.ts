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

export default defineConfig({
  plugins: [react(), dropJarvisFixtures()],
  server: {
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
    setupFiles: ['./src/test/setup.ts'],
    testTimeout: 15000,
    coverage: {
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/api/types.ts',
        'src/main.tsx',
        'src/test/**',
        'src/**/*.test.ts',
        'src/**/*.test.tsx',
        'src/**/testFixtures.tsx',
        'src/**/index.ts',
        '**/*.css',
        '**/.impeccable/**'
      ]
    }
  }
});
