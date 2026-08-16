import type { Lang } from '../../i18n/I18nContext';

const locales: Record<Lang, string> = { ru: 'ru-RU', en: 'en-US' };

export const DASH = '—';

export const formatNumber = (lang: Lang, value: number, digits = 0): string => {
  const format = new Intl.NumberFormat(locales[lang], { maximumFractionDigits: digits });
  const text = format.format(value);
  return text === format.format(-0) ? format.format(0) : text;
};

export const formatPercent = (lang: Lang, value: number): string =>
  new Intl.NumberFormat(locales[lang], {
    style: 'percent',
    maximumFractionDigits: 1
  }).format(value);

export const formatStepDate = (lang: Lang, iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return DASH;
  }
  return new Intl.DateTimeFormat(locales[lang], {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC'
  }).format(date);
};
