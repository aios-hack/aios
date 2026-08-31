import type {
  HierarchyFile,
  HierarchyGroupAllocation,
  HierarchyGroupLevel,
  HierarchyStep,
  HierarchyWellDecision
} from '../../api/types';
import { groupColor } from '../../theme/tokens';

export const UNGROUPED = 'ungrouped';

export const TOP_ALLOCATIONS = 5;

export interface CouncilPath {
  well: string;
  group: string | null;
}

export interface FieldSegment {
  group: string;
  limit: number;
  share: number | null;
  color: string;
}

export interface GroupCard {
  group: string;
  received: number;
  color: string;
  top: HierarchyGroupAllocation[];
  rest: number;
  restTotal: number;
}

export interface WellRow extends HierarchyWellDecision {
  color: string | null;
}

export const groupOrder = (file: HierarchyFile): Map<string, number> =>
  new Map(file.groups.map((group, index) => [group, index]));

export const colorOf = (order: Map<string, number>, group: string | null): string | null =>
  group === null ? null : groupColor(order.get(group) ?? 0);

export const stepFor = (file: HierarchyFile, index: number): HierarchyStep | null =>
  Number.isInteger(index) && index >= 0 && index < file.steps.length
    ? file.steps[index]
    : null;

export const fieldSegments = (
  step: HierarchyStep,
  order: Map<string, number>
): FieldSegment[] => {
  const total = step.field.injection_limit_m3_per_day;
  return step.field.allocations.map((allocation) => ({
    group: allocation.group,
    limit: allocation.limit_m3_per_day,
    share: total > 0 ? allocation.limit_m3_per_day / total : null,
    color: colorOf(order, allocation.group) ?? ''
  }));
};

const restTotalOf = (rest: readonly HierarchyGroupAllocation[]): number =>
  rest.reduce((sum, item) => sum + item.value_m3_per_day, 0);

export const groupCard = (
  level: HierarchyGroupLevel,
  order: Map<string, number>
): GroupCard => {
  const sorted = [...level.allocations].sort(
    (a, b) => b.value_m3_per_day - a.value_m3_per_day
  );
  const rest = sorted.slice(TOP_ALLOCATIONS);
  return {
    group: level.group,
    received: level.received_m3_per_day,
    color: colorOf(order, level.group) ?? '',
    top: sorted.slice(0, TOP_ALLOCATIONS),
    rest: rest.length,
    restTotal: restTotalOf(rest)
  };
};

export const ungroupedAllocations = (step: HierarchyStep): HierarchyGroupAllocation[] =>
  step.ungrouped ?? [];

export const ungroupedWells = (step: HierarchyStep): HierarchyWellDecision[] =>
  step.wells.filter((well) => well.group === null);

export const hasUngrouped = (file: HierarchyFile, step: HierarchyStep): boolean =>
  file.ungrouped.length > 0 ||
  ungroupedAllocations(step).length > 0 ||
  ungroupedWells(step).length > 0;

export const wellsOf = (
  step: HierarchyStep,
  group: string | null,
  order: Map<string, number>
): WellRow[] =>
  step.wells
    .filter((well) => well.group === group)
    .map((well) => ({ ...well, color: colorOf(order, well.group) }));

export const pathOf = (step: HierarchyStep, well: string | null): CouncilPath | null => {
  if (well === null) {
    return null;
  }
  const row = step.wells.find((entry) => entry.well === well);
  return row === undefined ? null : { well: row.well, group: row.group };
};

export const groupKey = (group: string | null): string => group ?? UNGROUPED;

export const isOnPath = (path: CouncilPath | null, group: string | null): boolean =>
  path !== null && path.group === group;

export const dimState = (path: CouncilPath | null, active: boolean): string =>
  path === null ? 'idle' : active ? 'path' : 'dim';
