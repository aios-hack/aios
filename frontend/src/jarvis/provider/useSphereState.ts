import { useMemo, useState } from 'react';
import type { JarvisSphereValue } from '@/jarvis/model/jarvisValue';
import type { SceneError } from '@/jarvis/model/scenes';
import type { SphereState } from '@/jarvis/sphere/lib/sphereState';
import type { JarvisStatusState } from '@/jarvis/transport/events';

interface SphereInputs {
  sceneError: SceneError | null;
  status: JarvisStatusState | null;
  micOpen: boolean;
}

export const useSphereState = ({
  sceneError,
  status,
  micOpen
}: SphereInputs): JarvisSphereValue => {
  const [hovering, setHovering] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);

  const sphereState = useMemo<SphereState>(() => {
    if (sceneError !== null) {
      return 'error';
    }
    if (micOpen) {
      return 'listening';
    }
    if (status === 'thinking' || status === 'tool') {
      return 'thinking';
    }
    if (status === 'composing') {
      return 'speaking';
    }
    return hovering ? 'hover' : 'idle';
  }, [sceneError, status, micOpen, hovering]);

  return useMemo(
    () => ({ sphereState, setHovering, audioLevel, setAudioLevel }),
    [sphereState, audioLevel]
  );
};
