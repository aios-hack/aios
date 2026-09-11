import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode
} from 'react';
import { clamp01 } from '@/shared/lib/math/clamp';

export interface MorphRequest {
  value: number;
  serial: number;
}

interface MorphContextValue {
  morphRequest: MorphRequest | null;
  requestMorph: (value: number) => void;
}

const MorphContext = createContext<MorphContextValue | null>(null);

export const MorphProvider = ({ children }: { children: ReactNode }) => {
  const [morphRequest, setMorphRequest] = useState<MorphRequest | null>(null);

  const requestMorph = useCallback(
    (value: number) =>
      setMorphRequest((current) => ({
        value: clamp01(value),
        serial: (current?.serial ?? 0) + 1
      })),
    []
  );

  const value = useMemo<MorphContextValue>(
    () => ({ morphRequest, requestMorph }),
    [morphRequest, requestMorph]
  );

  return <MorphContext.Provider value={value}>{children}</MorphContext.Provider>;
};

export const useMorphRequest = (): MorphRequest | null =>
  useContext(MorphContext)?.morphRequest ?? null;

export const useRequestMorph = (): ((value: number) => void) => {
  const value = useContext(MorphContext);
  return value?.requestMorph ?? (() => undefined);
};
