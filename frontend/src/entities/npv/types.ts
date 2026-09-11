import type { ArtifactMeta } from '@/shared/api/artifact';

export interface NpvWellRow {
  well: string;
  pre_tax: number;
  with_allocated_tax: number;
}

export interface NpvTotals {
  pre_tax: number;
  with_allocated_tax: number;
}

export interface NpvFile {
  meta?: ArtifactMeta;
  wells: NpvWellRow[];
  total: NpvTotals;
  npv_methodology: number;
}
