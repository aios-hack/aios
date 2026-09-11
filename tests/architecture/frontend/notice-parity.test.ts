import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { NOTICE_KEYS } from '@/shared/api/notice';
import { repoPath } from '@support/paths';

const PREFIX = 'showcase.notice.';

const backendCatalog = (lang: string): Record<string, string> =>
  JSON.parse(readFileSync(repoPath('backend', 'shared', 'i18n', `${lang}.json`), 'utf-8'));

const frontendNamespace = (lang: string): Record<string, string> =>
  JSON.parse(
    readFileSync(repoPath('frontend', 'src', 'shared', 'i18n', 'locales', lang, 'showcase.json'), 'utf-8')
  );

describe('showcase notice keys', () => {
  it('declares exactly the keys the backend catalog carries', () => {
    for (const lang of ['ru', 'en']) {
      const backend = Object.keys(backendCatalog(lang))
        .filter((key) => key.startsWith(PREFIX))
        .sort();
      expect(backend, lang).toEqual([...NOTICE_KEYS].sort());
    }
  });

  it('carries the backend text verbatim in both languages', () => {
    for (const lang of ['ru', 'en']) {
      const backend = backendCatalog(lang);
      const frontend = frontendNamespace(lang);
      for (const key of NOTICE_KEYS) {
        expect(frontend[key.slice('showcase.'.length)], `${lang}:${key}`).toBe(backend[key]);
      }
    }
  });
});
