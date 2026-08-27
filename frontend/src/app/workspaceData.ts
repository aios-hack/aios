import type { DatasetName } from '../data';
import type { Workspace } from '../state/ConsoleContext';

export const WORKSPACE_DATASETS: Record<Workspace, readonly DatasetName[]> = {
  overview: ['timeline', 'npv'],
  field: ['wells', 'graph', 'timeline'],
  history: ['timeline', 'npv', 'graph'],
  decisions: ['hierarchy', 'ablation', 'trace'],
  money: ['npv', 'scenarios', 'timeline', 'ablation']
};

export const datasetsFor = (workspace: Workspace): readonly DatasetName[] =>
  WORKSPACE_DATASETS[workspace];
