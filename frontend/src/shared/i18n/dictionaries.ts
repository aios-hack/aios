export type Lang = 'ru' | 'en';

type Namespace = Record<string, string>;

const modules = import.meta.glob<Namespace>('./locales/*/*.json', {
  eager: true,
  import: 'default'
});

const COMMON = 'common';

const parse = (path: string): { lang: Lang; namespace: string } | null => {
  const match = /\.\/locales\/(ru|en)\/([a-z0-9-]+)\.json$/.exec(path);
  if (match === null) {
    return null;
  }
  return { lang: match[1] as Lang, namespace: match[2] as string };
};

const prefixed = (namespace: string, entries: Namespace): Namespace =>
  namespace === COMMON
    ? { ...entries }
    : Object.fromEntries(
        Object.entries(entries).map(([key, value]) => [`${namespace}.${key}`, value])
      );

const build = (): Record<Lang, Namespace> => {
  const result: Record<Lang, Namespace> = { ru: {}, en: {} };
  for (const [path, entries] of Object.entries(modules)) {
    const parsed = parse(path);
    if (parsed === null) {
      continue;
    }
    Object.assign(result[parsed.lang], prefixed(parsed.namespace, entries));
  }
  return result;
};

export const dictionaries: Record<Lang, Namespace> = build();
