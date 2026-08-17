import type {
  GraphFile,
  NpvFile,
  ScenariosFile,
  TimelineFile,
  TraceFile,
  WellsFile
} from '../api/types';
import {
  isGraphFile,
  isNpvFile,
  isScenariosFile,
  isTimelineFile,
  isTraceFile,
  isWellsFile
} from './validators';

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
}

export type DatasetName = keyof DatasetMap;

type DatasetRegistry = { [K in DatasetName]: DatasetSpec<DatasetMap[K]> };

export const DATASETS: DatasetRegistry = {
  timeline: { file: 'timeline.json', scope: 'scenario', validate: isTimelineFile },
  trace: { file: 'trace.json', scope: 'scenario', validate: isTraceFile },
  wells: { file: 'wells.json', scope: 'scenario', validate: isWellsFile },
  npv: { file: 'npv.json', scope: 'scenario', validate: isNpvFile },
  graph: { file: 'graph.json', scope: 'scenario', validate: isGraphFile },
  scenarios: { file: 'scenarios.json', scope: 'global', validate: isScenariosFile }
};
