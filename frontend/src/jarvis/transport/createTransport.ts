import { createMockTransport } from './mockTransport';
import { createSseTransport } from './sseTransport';
import type { JarvisTransport } from './JarvisTransport';

export type TransportMode = 'mock' | 'sse';

export const readTransportMode = (raw: string | undefined, testing: boolean): TransportMode => {
  if (raw === 'sse') {
    return 'sse';
  }
  if (raw === 'mock') {
    return 'mock';
  }
  return testing ? 'mock' : 'sse';
};

interface FactoryOptions {
  mode?: TransportMode;
  onDegrade?: () => void;
}

export const createTransport = ({ mode, onDegrade }: FactoryOptions = {}): JarvisTransport => {
  const env = import.meta.env as Record<string, string | boolean | undefined>;
  const resolved =
    mode ??
    readTransportMode(
      typeof env.VITE_JARVIS_TRANSPORT === 'string' ? env.VITE_JARVIS_TRANSPORT : undefined,
      env.MODE === 'test' || env.VITEST === true
    );
  if (resolved === 'mock') {
    return createMockTransport();
  }
  return createSseTransport({ fallback: createMockTransport(), onDegrade });
};
