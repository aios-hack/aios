import type { AblationFile } from '@/entities/ablation/types';
import { isAbsent, isArtifactMeta, isFilledArray, isNum, isNumOrNull, isRecord, isStr } from '@/shared/api/guards';

const isAblationRule = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.rule) &&
  typeof data.enabled === 'boolean' &&
  isNumOrNull(data.delta_npv) &&
  isNumOrNull(data.share) &&
  (isAbsent(data.disabled_reason) || isStr(data.disabled_reason));

export const isAblationFile = (data: unknown): data is AblationFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isNum(data.npv_total) &&
  isFilledArray(data.rules) &&
  data.rules.every(isAblationRule);
