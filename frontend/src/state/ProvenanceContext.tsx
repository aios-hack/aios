import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useDataset } from '../data';

export interface ProvenanceValue {
  provenance: string;
}

const ProvenanceContext = createContext<ProvenanceValue | null>(null);

export const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
  const source = useDataset('timeline');

  const value = useMemo<ProvenanceValue>(() => {
    if (source.status !== 'ready') {
      return { provenance: '' };
    }
    const meta = source.data.meta;
    return {
      provenance: meta?.provenance ?? ''
    };
  }, [source]);

  return (
    <ProvenanceContext.Provider value={value}>{children}</ProvenanceContext.Provider>
  );
};

const DETACHED: ProvenanceValue = { provenance: '' };

export const useProvenance = (): ProvenanceValue =>
  useContext(ProvenanceContext) ?? DETACHED;
