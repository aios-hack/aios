import { useMemo } from 'react';
import { useDataset, type DatasetName } from '../data';
import type { Workspace } from '../state/ConsoleContext';
import { datasetsFor } from './workspaceData';

export type WorkspaceDataStatus = 'loading' | 'error' | 'ready';

export const useWorkspaceData = (workspace: Workspace): WorkspaceDataStatus => {
  const timeline = useDataset('timeline');
  const trace = useDataset('trace');
  const wells = useDataset('wells');
  const npv = useDataset('npv');
  const graph = useDataset('graph');
  const scenarios = useDataset('scenarios');
  const ablation = useDataset('ablation');
  const hierarchy = useDataset('hierarchy');

  return useMemo(() => {
    const states: Record<DatasetName, { status: string }> = {
      timeline,
      trace,
      wells,
      npv,
      graph,
      scenarios,
      ablation,
      hierarchy,
      demoScript: { status: 'ready' }
    };
    const required = datasetsFor(workspace);
    if (required.some((name) => states[name]?.status === 'error')) {
      return 'error';
    }
    if (required.some((name) => states[name]?.status === 'loading')) {
      return 'loading';
    }
    return 'ready';
  }, [workspace, timeline, trace, wells, npv, graph, scenarios, ablation, hierarchy]);
};
