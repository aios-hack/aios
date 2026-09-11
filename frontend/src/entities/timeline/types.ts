import type { ArtifactMeta } from '@/shared/api/artifact';
import type { WellAvailability, WellOperatingStatus, WellRole } from '@/entities/wells/types';

export interface TimelineWellRow {
  well: string;
  availability: WellAvailability;
  role: WellRole;
  operating_status: WellOperatingStatus;
  setpoint: number;
  liquid_rate: number;
  injection_rate: number;
  bhp: number;
  watercut: number | null;
  fact_to_target: number | null;
  cumulative_liquid: number;
  explanation?: string | null;
}


export interface TimelineFieldStats {
  production: number | null;
  injection: number | null;
  compensation: number | null;
  compensation_surface?: number | null;
  compensation_reservoir?: number | null;
  compensation_defined?: boolean | null;
  npv_cumulative: number;
  active_wells: number;
}

export interface TimelineStep {
  control_step: number;
  date: string;
  terminal: boolean;
  field: TimelineFieldStats;
  wells: TimelineWellRow[];
}

export type CompensationBasis = 'surface' | 'reservoir';

export interface FieldNormBand {
  min: number;
  max: number;
  source?: string;
  enforcement?: string;
  scope?: string;
  basis?: CompensationBasis;
}

export interface TimelineFieldNorms {
  compensation?: FieldNormBand;
}

export interface TimelineFile {
  meta?: ArtifactMeta;
  model: string;
  t0: string;
  n_control_dates: number;
  n_intervals: number;
  wells: string[];
  steps: TimelineStep[];
  field_norms?: TimelineFieldNorms;
}
