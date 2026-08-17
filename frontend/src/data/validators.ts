import type {
  GraphFile,
  NpvFile,
  ScenariosFile,
  TimelineFile,
  TraceFile,
  WellsFile
} from '../api/types';

const isRecord = (data: unknown): data is Record<string, unknown> =>
  typeof data === 'object' && data !== null && !Array.isArray(data);

export const isTimelineFile = (data: unknown): data is TimelineFile =>
  isRecord(data) && Array.isArray(data.steps) && data.steps.length > 0;

export const isTraceFile = (data: unknown): data is TraceFile => isRecord(data);

export const isGraphFile = (data: unknown): data is GraphFile => {
  if (!isRecord(data)) {
    return false;
  }
  const candidate = data as Partial<GraphFile>;
  return (
    Array.isArray(candidate.nodes) &&
    candidate.nodes.length > 0 &&
    Array.isArray(candidate.edges) &&
    typeof candidate.window === 'object' &&
    candidate.window !== null &&
    typeof candidate.window.start === 'string' &&
    typeof candidate.window.end === 'string'
  );
};

export const isNpvFile = (data: unknown): data is NpvFile =>
  isRecord(data) &&
  Array.isArray(data.wells) &&
  data.wells.length > 0 &&
  typeof data.total === 'object' &&
  data.total !== null;

export const isScenariosFile = (data: unknown): data is ScenariosFile =>
  isRecord(data) && Array.isArray(data.scenarios);

const isGridSize = (data: unknown): boolean =>
  isRecord(data) &&
  typeof data.ni === 'number' &&
  typeof data.nj === 'number' &&
  typeof data.nk === 'number';

const isWellPoint = (data: unknown): boolean =>
  isRecord(data) &&
  typeof data.id === 'string' &&
  typeof data.i === 'number' &&
  typeof data.j === 'number' &&
  Array.isArray(data.layers) &&
  Array.isArray(data.completions);

export const isWellsFile = (data: unknown): data is WellsFile =>
  isRecord(data) &&
  isGridSize(data.grid) &&
  Array.isArray(data.layers) &&
  Array.isArray(data.wells) &&
  data.wells.every(isWellPoint);
