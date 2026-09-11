import type { Translate } from '@/shared/i18n/I18nContext';

export const translateOr = (t: Translate, key: string, fallbackKey: string): string => {
  const text = t(key);
  return text === key ? t(fallbackKey) : text;
};
