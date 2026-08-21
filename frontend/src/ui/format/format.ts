import type { Lang } from '../../i18n/I18nContext';

const locales: Record<Lang, string> = { ru: 'ru-RU', en: 'en-US' };

export const DASH = '—';

const numberFormats = new Map<string, Intl.NumberFormat>();
const percentFormats = new Map<Lang, Intl.NumberFormat>();
const dateFormats = new Map<Lang, Intl.DateTimeFormat>();

const numberFormat = (lang: Lang, digits: number): Intl.NumberFormat => {
  const key = `${lang}:${digits}`;
  const cached = numberFormats.get(key);
  if (cached !== undefined) {
    return cached;
  }
  const format = new Intl.NumberFormat(locales[lang], { maximumFractionDigits: digits });
  numberFormats.set(key, format);
  return format;
};

const percentFormat = (lang: Lang): Intl.NumberFormat => {
  const cached = percentFormats.get(lang);
  if (cached !== undefined) {
    return cached;
  }
  const format = new Intl.NumberFormat(locales[lang], {
    style: 'percent',
    maximumFractionDigits: 1
  });
  percentFormats.set(lang, format);
  return format;
};

const dateFormat = (lang: Lang): Intl.DateTimeFormat => {
  const cached = dateFormats.get(lang);
  if (cached !== undefined) {
    return cached;
  }
  const format = new Intl.DateTimeFormat(locales[lang], {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC'
  });
  dateFormats.set(lang, format);
  return format;
};

export const formatNumber = (lang: Lang, value: number, digits = 0): string => {
  const format = numberFormat(lang, digits);
  const text = format.format(value);
  return text === format.format(-0) ? format.format(0) : text;
};

export const formatPercent = (lang: Lang, value: number): string =>
  percentFormat(lang).format(value);

export const formatStepDate = (lang: Lang, iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return DASH;
  }
  return dateFormat(lang).format(date);
};
