import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
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
