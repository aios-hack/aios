import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

export const repoPath = (...parts: string[]): string =>
  resolve(HERE, '..', '..', '..', ...parts);

export const frontendPath = (...parts: string[]): string =>
  repoPath('frontend', ...parts);

export const srcPath = (...parts: string[]): string => frontendPath('src', ...parts);

export const publicPath = (...parts: string[]): string =>
  frontendPath('public', ...parts);

export const testsPath = (...parts: string[]): string => repoPath('tests', ...parts);

export const joinPath = (...parts: string[]): string => join(...parts);
