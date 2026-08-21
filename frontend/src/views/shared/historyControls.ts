export type HistoryView = 'matrix' | 'wall' | 'table';

export type HistoryMetric = 'watercut' | 'mode' | 'ratio' | 'npv';

export const HISTORY_METRICS: readonly HistoryMetric[] = [
  'watercut',
  'mode',
  'ratio',
  'npv'
];

export type HistorySort = 'well' | 'group' | 'npv' | 'watercut';

export const HISTORY_SORTS: readonly HistorySort[] = ['well', 'group', 'npv', 'watercut'];

export const metricAvailableIn = (view: HistoryView): boolean => view === 'matrix';

export const sortAvailableIn = (_view: HistoryView): boolean => true;
