import type { ArtifactMeta } from '@/shared/api/artifact';

export interface HierarchyFieldAllocation {
  group: string;
  limit_m3_per_day: number;
}

export interface HierarchyFieldLevel {
  injection_limit_m3_per_day: number;
  water_available_m3_per_day: number | null;
  allocations: HierarchyFieldAllocation[];
}

export interface HierarchyGroupAllocation {
  well: string;
  value_m3_per_day: number;
}

export interface HierarchyGroupLevel {
  group: string;
  received_m3_per_day: number;
  allocations: HierarchyGroupAllocation[];
}

export interface HierarchyWellDecision {
  well: string;
  group: string | null;
  decision: string;
  rule: string;
  inputs: Record<string, number>;
  constraint: string | null;
}

export interface HierarchyStep {
  control_step: number;
  field: HierarchyFieldLevel;
  groups: HierarchyGroupLevel[];
  ungrouped?: HierarchyGroupAllocation[];
  wells: HierarchyWellDecision[];
}

export interface HierarchyFile {
  meta?: ArtifactMeta;
  n_control_dates: number;
  groups: string[];
  ungrouped: string[];
  steps: HierarchyStep[];
}

export interface HierarchyIndexFile {
  meta?: ArtifactMeta;
  n_control_dates: number;
  groups: string[];
  ungrouped: string[];
  agents?: unknown[];
  step_count: number;
  step_path: string;
}
