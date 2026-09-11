import type { ComparisonFile, RunsResponse } from '@/entities/runs/types';
import type { ResourceState } from '@/shared/api/ResourceState';
import { useJsonResource } from '@/shared/api/useJsonResource';
import { isComparisonFile, isRunsResponse } from '@/entities/runs/validate';

export const RUNS_URL = '/api/runs';

export const comparisonUrl = (runId: string): string =>
  `/api/runs/${encodeURIComponent(runId)}/comparison`;

export const useRuns = (): ResourceState<RunsResponse> =>
  useJsonResource(RUNS_URL, isRunsResponse);

export const useComparison = (runId: string | null): ResourceState<ComparisonFile> =>
  useJsonResource(runId === null ? null : comparisonUrl(runId), isComparisonFile);
