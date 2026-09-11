import { useMemo } from 'react';
import { useDataset, type DatasetName } from '@/entities';
import type { Workspace } from '@/shared/router/routes';
import { datasetsFor } from '@/app/ConsoleScene/workspaceData';

export type WorkspaceDataStatus = 'loading' | 'error' | 'ready';

export const useWorkspaceData = (workspace: Workspace): WorkspaceDataStatus => {
  const timeline = useDataset('timeline');
  const trace = useDataset('trace');
  const wells = useDataset('wells');
  const npv = useDataset('npv');
  const graph = useDataset('graph');
  const scenarios = useDataset('scenarios');
  const ablation = useDataset('ablation');
  const hierarchyIndex = useDataset('hierarchy-index');

  return useMemo(() => {
    const states: Partial<Record<DatasetName, { status: string }>> = {
      timeline,
      trace,
      wells,
      npv,
      graph,
      scenarios,
      ablation,
      'hierarchy-index': hierarchyIndex
    };
    const required = datasetsFor(workspace);
    if (required.some((name) => states[name]?.status === 'error')) {
      return 'error';
    }
    if (required.some((name) => states[name]?.status === 'loading')) {
      return 'loading';
    }
    return 'ready';
  }, [workspace, timeline, trace, wells, npv, graph, scenarios, ablation, hierarchyIndex]);
};
