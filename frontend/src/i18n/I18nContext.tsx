import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { dictionaries, type Lang } from './dictionaries';

export type { Lang } from './dictionaries';
export type Translate = (key: string, params?: Record<string, string | number>) => string;

const STORAGE_KEY = 'aios-lang';

interface I18nContextValue {
  lang: Lang;
  toggleLang: () => void;
  t: Translate;
}

const I18nContext = createContext<I18nContextValue | null>(null);

const readStoredLang = (): Lang => {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'ru';
  } catch {
    return 'ru';
  }
};

const translate = (lang: Lang, key: string, params?: Record<string, string | number>): string => {
  const template = dictionaries[lang][key] ?? key;
  if (!params) {
    return template;
  }
  return Object.entries(params).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
    template
  );
};

export const I18nProvider = ({ children }: { children: ReactNode }) => {
  const [lang, setLang] = useState<Lang>(readStoredLang);

  const toggleLang = useCallback(
    () =>
      setLang((current) => {
        const next: Lang = current === 'ru' ? 'en' : 'ru';
        try {
          localStorage.setItem(STORAGE_KEY, next);
        } catch {
          return next;
        }
        return next;
      }),
    []
  );

  const t = useCallback<Translate>((key, params) => translate(lang, key, params), [lang]);

  const value = useMemo<I18nContextValue>(
    () => ({ lang, toggleLang, t }),
    [lang, toggleLang, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export const useI18n = (): I18nContextValue => {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error('useI18n must be used within I18nProvider');
  }
  return value;
};

export const useT = (): Translate => useI18n().t;

export const useFallbackT = (): Translate => {
  const value = useContext(I18nContext);
  const lang: Lang = value === null ? 'ru' : value.lang;
  return useCallback<Translate>((key, params) => translate(lang, key, params), [lang]);
};
