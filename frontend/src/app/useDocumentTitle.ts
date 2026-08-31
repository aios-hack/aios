import { useEffect } from 'react';
import type { Lang } from '../i18n/I18nContext';
import { buildDocumentTitle, type TitleParts } from './documentTitle';

export const useDocumentTitle = (parts: TitleParts, lang: Lang): void => {
  const { section, view, scenario, suffix } = parts;

  useEffect(() => {
    document.title = buildDocumentTitle({ section, view, scenario, suffix });
    document.documentElement.lang = lang;
  }, [section, view, scenario, suffix, lang]);
};
