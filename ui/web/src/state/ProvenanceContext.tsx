import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useOptionalScenario } from './ScenarioContext';
import { useJsonResource } from './TimelineContext';

export interface ProvenanceValue {
  synthetic: boolean;
  provenance: string;
}

interface MetaCarrier {
  meta?: { provenance?: unknown; synthetic?: unknown };
}

const isMetaCarrier = (data: unknown): data is MetaCarrier =>
  typeof data === 'object' && data !== null;

const ProvenanceContext = createContext<ProvenanceValue | null>(null);

export const ProvenanceProvider = ({ children }: { children: ReactNode }) => {
  const { dataUrl } = useOptionalScenario();
  const source = useJsonResource(dataUrl('timeline.json'), isMetaCarrier);

  const value = useMemo<ProvenanceValue>(() => {
    if (source.status !== 'ready') {
      return { synthetic: false, provenance: '' };
    }
    const meta = source.data.meta;
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
