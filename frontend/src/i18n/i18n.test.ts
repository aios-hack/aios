import { describe, expect, it } from 'vitest';

const toNamespaces = (
  modules: Record<string, unknown>
): Record<string, Record<string, string>> =>
  Object.fromEntries(
    Object.entries(modules).map(([path, module]) => [
      path.replace(/^.*\/([^/]+)\.json$/, '$1'),
      (module as { default: Record<string, string> }).default
    ])
  );

const ru = toNamespaces(import.meta.glob('./ru/*.json', { eager: true }));
const en = toNamespaces(import.meta.glob('./en/*.json', { eager: true }));

describe('i18n dictionaries', () => {
  it('has identical namespace lists in ru and en', () => {
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(ru).length).toBeGreaterThan(0);
  });

  it('has identical key sets in ru and en for every namespace', () => {
    for (const namespace of Object.keys(ru)) {
      expect(Object.keys(ru[namespace]).sort(), namespace).toEqual(
        Object.keys(en[namespace] ?? {}).sort()
      );
    }
  });

  it('has non-empty string values', () => {
    for (const locale of [ru, en]) {
      for (const [namespace, entries] of Object.entries(locale)) {
        for (const [key, value] of Object.entries(entries)) {
          expect(typeof value, `${namespace}:${key}`).toBe('string');
          expect(value.length, `${namespace}:${key}`).toBeGreaterThan(0);
        }
      }
    }
  });
});
