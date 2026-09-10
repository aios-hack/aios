import type { ComparisonFile, RunsResponse } from '../api/types';
import type { ResourceState } from './ResourceState';
import { useJsonResource } from './useJsonResource';
import { isComparisonFile, isRunsResponse } from './validators';

export const RUNS_URL = '/api/runs';

export const comparisonUrl = (runId: string): string =>
  `/api/runs/${encodeURIComponent(runId)}/comparison`;

export const useRuns = (): ResourceState<RunsResponse> =>
  useJsonResource(RUNS_URL, isRunsResponse);

export const useComparison = (runId: string | null): ResourceState<ComparisonFile> =>
  useJsonResource(runId === null ? null : comparisonUrl(runId), isComparisonFile);
