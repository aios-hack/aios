import { createMockTransport } from '@/jarvis/transport/mockTransport';
import { createSseTransport } from '@/jarvis/transport/sseTransport';
import type { JarvisTransport } from '@/jarvis/transport/JarvisTransport';

export type TransportMode = 'mock' | 'sse';

export const readTransportMode = (raw: string | undefined, testing: boolean): TransportMode => {
  if (raw === 'sse') {
    return 'sse';
  }
  if (raw === 'mock' && testing) {
    return 'mock';
  }
  return testing ? 'mock' : 'sse';
};

interface FactoryOptions {
  mode?: TransportMode;
}

export const createTransport = ({ mode }: FactoryOptions = {}): JarvisTransport => {
  const env = import.meta.env as Record<string, string | boolean | undefined>;
  const testing = env.MODE === 'test' || env.VITEST === true;
  const resolved =
    mode ??
    readTransportMode(
      typeof env.VITE_JARVIS_TRANSPORT === 'string' ? env.VITE_JARVIS_TRANSPORT : undefined,
      testing
    );
  if (resolved === 'mock' && testing) {
    return createMockTransport();
  }
  return createSseTransport();
};
