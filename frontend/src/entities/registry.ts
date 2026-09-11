import type { AblationFile } from '@/entities/ablation/types';
import { isAblationFile } from '@/entities/ablation/validate';
import type { GraphFile } from '@/entities/graph/types';
import { isGraphFile } from '@/entities/graph/validate';
import type { HierarchyIndexFile } from '@/entities/hierarchy/types';
import { isHierarchyIndexFile } from '@/entities/hierarchy/validate';
import type { MapsIndexFile } from '@/entities/maps/types';
import { isMapsIndexFile } from '@/entities/maps/validate';
import type { NpvFile } from '@/entities/npv/types';
import { isNpvFile } from '@/entities/npv/validate';
import type { ScenariosFile } from '@/entities/scenarios/types';
import { isScenariosFile } from '@/entities/scenarios/validate';
import type { TimelineFile } from '@/entities/timeline/types';
import { isTimelineFile } from '@/entities/timeline/validate';
import type { TraceFile } from '@/entities/trace/types';
import { isTraceFile } from '@/entities/trace/validate';
import type { WellsFile } from '@/entities/wells/types';
import { isWellsFile } from '@/entities/wells/validate';

export type DatasetScope = 'scenario' | 'global';

export interface DatasetSpec<T> {
  file: string;
  scope: DatasetScope;
  validate: (data: unknown) => data is T;
}

export interface DatasetMap {
  timeline: TimelineFile;
  trace: TraceFile;
  wells: WellsFile;
  npv: NpvFile;
  graph: GraphFile;
  scenarios: ScenariosFile;
  ablation: AblationFile;
  'hierarchy-index': HierarchyIndexFile;
  'maps-index': MapsIndexFile;
}

export type DatasetName = keyof DatasetMap;

type DatasetRegistry = { [K in DatasetName]: DatasetSpec<DatasetMap[K]> };

export const DATASETS: DatasetRegistry = {
  timeline: { file: 'timeline.json', scope: 'scenario', validate: isTimelineFile },
  trace: { file: 'trace.json', scope: 'scenario', validate: isTraceFile },
  wells: { file: 'wells.json', scope: 'global', validate: isWellsFile },
  npv: { file: 'npv.json', scope: 'scenario', validate: isNpvFile },
  graph: { file: 'graph.json', scope: 'scenario', validate: isGraphFile },
  scenarios: { file: 'scenarios.json', scope: 'global', validate: isScenariosFile },
  ablation: { file: 'ablation.json', scope: 'scenario', validate: isAblationFile },
  'hierarchy-index': {
    file: 'hierarchy-index.json',
    scope: 'scenario',
    validate: isHierarchyIndexFile
  },
  'maps-index': { file: 'maps/index.json', scope: 'global', validate: isMapsIndexFile }
};
