import type { Lang } from '@/shared/i18n/dictionaries';
import { formatNumber } from '@/shared/lib/format';

const RUBLE = '\u20bd';

export const formatMoney = (
  lang: Lang,
  value: number | null | undefined
): string | null =>
  value === null || value === undefined
    ? null
    : `${formatNumber(lang, value, 0)} ${RUBLE}`;

export const formatSignedPercent = (
  lang: Lang,
  value: number | null | undefined
): string | null =>
  value === null || value === undefined ? null : `${formatNumber(lang, value, 2)}%`;

export const forecastDrift = (predicted: number, verified: number): number =>
  (100 * Math.abs(predicted - verified)) / Math.max(1, Math.abs(verified));
