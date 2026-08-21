import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { HistoryMetric, HistorySort } from '../views/shared/historyControls';

interface HistoryViewContextValue {
  metric: HistoryMetric;
  setMetric: (metric: HistoryMetric) => void;
  sort: HistorySort;
  setSort: (sort: HistorySort) => void;
}

const HistoryViewContext = createContext<HistoryViewContextValue | null>(null);

export const HistoryViewProvider = ({ children }: { children: ReactNode }) => {
  const [metric, setMetric] = useState<HistoryMetric>('watercut');
  const [sort, setSort] = useState<HistorySort>('well');

  const value = useMemo<HistoryViewContextValue>(
    () => ({ metric, setMetric, sort, setSort }),
    [metric, sort]
  );

  return (
    <HistoryViewContext.Provider value={value}>{children}</HistoryViewContext.Provider>
  );
};

export const useHistoryView = (): HistoryViewContextValue => {
  const value = useContext(HistoryViewContext);
  if (!value) {
    throw new Error('useHistoryView must be used within HistoryViewProvider');
  }
  return value;
};
