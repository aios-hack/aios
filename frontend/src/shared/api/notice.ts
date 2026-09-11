import type { ArtifactMeta } from '@/shared/api/artifact';
import type { Translate } from '@/shared/i18n/I18nContext';

export const NOTICE_KEYS = [
  'showcase.notice.ablation_absent',
  'showcase.notice.champion',
  'showcase.notice.demo',
  'showcase.notice.graph_lambda_absent',
  'showcase.notice.graph_lambda_measured',
  'showcase.notice.hierarchy',
  'showcase.notice.plan',
  'showcase.notice.plan_unstable',
  'showcase.notice.real'
] as const;

export type NoticeKey = (typeof NOTICE_KEYS)[number];

const KNOWN: ReadonlySet<string> = new Set(NOTICE_KEYS);

export const isNoticeKey = (value: unknown): value is NoticeKey =>
  typeof value === 'string' && KNOWN.has(value);

export const noticeTextOf = (
  t: Translate,
  meta: ArtifactMeta | undefined
): string | null => {
  if (meta === undefined) {
    return null;
  }
  if (isNoticeKey(meta.notice_key)) {
    return t(meta.notice_key);
  }
  const served = meta.notice;
  return typeof served === 'string' && served.length > 0 ? served : null;
};
