export type HistoryMetric = 'watercut' | 'mode' | 'ratio' | 'npv';

export const HISTORY_METRICS: readonly HistoryMetric[] = [
  'watercut',
  'mode',
  'ratio',
  'npv'
];

export type HistorySort = 'well' | 'group' | 'npv' | 'watercut';

export const HISTORY_SORTS: readonly HistorySort[] = ['well', 'group', 'npv', 'watercut'];
