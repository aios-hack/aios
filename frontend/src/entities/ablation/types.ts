import type { ArtifactMeta } from '@/shared/api/artifact';

export interface AblationRule {
  rule: string;
  enabled: boolean;
  delta_npv: number | null;
  share: number | null;
  disabled_reason?: string;
}

export interface AblationFile {
  meta?: ArtifactMeta;
  npv_total: number;
  rules: AblationRule[];
}
