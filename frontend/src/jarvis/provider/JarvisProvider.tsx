import type { ReactNode } from 'react';
import {
  JarvisSessionContext,
  JarvisSphereContext,
  JarvisVoiceContext
} from '@/jarvis/provider/contexts';
import { useSessionValue } from '@/jarvis/provider/useSessionValue';
import { useSphereState } from '@/jarvis/provider/useSphereState';
import { useVoiceState } from '@/jarvis/provider/useVoiceState';
import type { JarvisTransport } from '@/jarvis/transport/JarvisTransport';

export const JarvisProvider = ({
  children,
  transport
}: {
  children: ReactNode;
  transport?: JarvisTransport;
}) => {
  const session = useSessionValue(transport);
  const voice = useVoiceState();
  const current = session.scenes.scenes[session.scenes.activeIndex];
  const sphere = useSphereState({
    sceneError: current?.error ?? null,
    status: session.scenes.status,
    micOpen: voice.micOpen
  });

  return (
    <JarvisSessionContext.Provider value={session}>
      <JarvisVoiceContext.Provider value={voice}>
        <JarvisSphereContext.Provider value={sphere}>{children}</JarvisSphereContext.Provider>
      </JarvisVoiceContext.Provider>
    </JarvisSessionContext.Provider>
  );
};
