import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useDataset } from '../data';

export interface ProvenanceValue {
  synthetic: boolean;
  provenance: string;
}

interface MetaCarrier {
  meta?: { provenance?: unknown; synthetic?: unknown };
}

const ProvenanceContext = createContext<ProvenanceValue | null>(null);

export const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
  const source = useDataset('timeline');

  const value = useMemo<ProvenanceValue>(() => {
    if (source.status !== 'ready') {
      return { synthetic: false, provenance: '' };
    }
    const meta = (source.data as MetaCarrier).meta;
    return {
      synthetic: meta?.synthetic === true,
      provenance: typeof meta?.provenance === 'string' ? meta.provenance : ''
    };
  }, [source]);

  return (
    <ProvenanceContext.Provider value={value}>{children}</ProvenanceContext.Provider>
  );
};

const DETACHED: ProvenanceValue = { synthetic: false, provenance: '' };

export const useProvenance = (): ProvenanceValue =>
  useContext(ProvenanceContext) ?? DETACHED;
