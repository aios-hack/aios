import type { Lang } from '../../i18n/I18nContext';

const locales: Record<Lang, string> = { ru: 'ru-RU', en: 'en-US' };

export const DASH = '—';

export const formatNumber = (lang: Lang, value: number, digits = 0): string =>
  new Intl.NumberFormat(locales[lang], { maximumFractionDigits: digits }).format(value);

export const formatPercent = (lang: Lang, value: number): string =>
  new Intl.NumberFormat(locales[lang], {
    style: 'percent',
    maximumFractionDigits: 1
  }).format(value);

export const formatStepDate = (lang: Lang, iso: string): string =>
  new Intl.DateTimeFormat(locales[lang], { month: 'long', year: 'numeric' }).format(
    new Date(iso)
  );
