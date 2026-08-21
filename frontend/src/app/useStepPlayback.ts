import type { Dispatch, SetStateAction } from 'react';
import { PLAY_INTERVAL_MS, PLAY_SPEEDS, playIntervalMs, usePlayback, type PlaySpeed } from '../state/PlaybackContext';

export { PLAY_INTERVAL_MS, PLAY_SPEEDS, playIntervalMs };
export type { PlaySpeed };

interface StepPlayback {
  playing: boolean;
  speed: PlaySpeed;
  setSpeed: (speed: PlaySpeed) => void;
  selectStep: (index: number) => void;
  onStep: (delta: number) => void;
  togglePlay: () => void;
}

export const useStepPlayback = (
  _stepCount: number,
  _stepIndex: number,
  _setStepIndex: Dispatch<SetStateAction<number>>
): StepPlayback => usePlayback();
