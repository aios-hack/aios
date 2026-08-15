import { createContext, useContext, useState, type ReactNode } from 'react';
import en from './en.json';
import ru from './ru.json';

export type Lang = 'ru' | 'en';
export type Translate = (key: string, params?: Record<string, string | number>) => string;

const STORAGE_KEY = 'aios-lang';
const dictionaries: Record<Lang, Record<string, string>> = { ru, en };

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

  const toggleLang = () =>
    setLang((current) => {
      const next: Lang = current === 'ru' ? 'en' : 'ru';
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        return next;
      }
      return next;
    });

  const t: Translate = (key, params) => translate(lang, key, params);

  return <I18nContext.Provider value={{ lang, toggleLang, t }}>{children}</I18nContext.Provider>;
};

export const useI18n = (): I18nContextValue => {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error('useI18n must be used within I18nProvider');
  }
  return value;
};

export const useT = (): Translate => useI18n().t;
