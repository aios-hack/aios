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

const sources = import.meta.glob('../**/*.{ts,tsx}', {
  eager: true,
  query: '?raw',
  import: 'default'
}) as Record<string, string>;

const code = Object.entries(sources)
  .filter(([path]) => !path.includes('.test.'))
  .map(([, text]) => text)
  .join('\n');

const isUsed = (fullKey: string): boolean => {
  if (code.includes(`'${fullKey}'`) || code.includes(`"${fullKey}"`)) {
    return true;
  }
  const parts = fullKey.split('.');
  const prefixUsed = parts
    .slice(0, -1)
    .some((_, index) =>
      code.includes(`\`${parts.slice(0, index + 1).join('.')}.\${`)
    );
  if (prefixUsed) {
    return true;
  }
  return parts
    .slice(1)
    .some((_, index) => code.includes(`}.${parts.slice(index + 1).join('.')}\``));
};

describe('i18n usage', () => {
  it('has no key that no source file references', () => {
    const unused: string[] = [];
    for (const [namespace, entries] of Object.entries(ru)) {
      for (const key of Object.keys(entries)) {
        const fullKey = namespace === 'common' ? key : `${namespace}.${key}`;
        if (!isUsed(fullKey)) {
          unused.push(fullKey);
        }
      }
    }
    expect(unused).toEqual([]);
  });
});
