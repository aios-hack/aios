import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
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
