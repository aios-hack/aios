import { useEffect } from 'react';
import type { Lang } from '../i18n/I18nContext';

export const useDocumentTitle = (section: string, suffix: string, lang: Lang): void => {
  useEffect(() => {
    document.title = `${section} · ${suffix}`;
    document.documentElement.lang = lang;
  }, [section, suffix, lang]);
};
