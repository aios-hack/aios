import {
  PLAY_INTERVAL_MS,
  PLAY_SPEED_MAX,
  PLAY_SPEED_MIN,
  PLAY_SPEED_STEP,
  playIntervalMs,
  usePlayback,
  type PlaySpeed
} from '../state/PlaybackContext';

export { PLAY_INTERVAL_MS, PLAY_SPEED_MAX, PLAY_SPEED_MIN, PLAY_SPEED_STEP, playIntervalMs };
export type { PlaySpeed };

interface StepPlayback {
  playing: boolean;
  speed: PlaySpeed;
  showDate: boolean;
  settingsOpen: boolean;
  setSpeed: (speed: PlaySpeed) => void;
  selectStep: (index: number) => void;
  onStep: (delta: number) => void;
  togglePlay: () => void;
}

export const useStepPlayback = (): StepPlayback => usePlayback();
