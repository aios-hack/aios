import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react';
import { useDataset } from '../../data';
import { useTimeline } from '../../state/TimelineContext';
import { DemoCaption } from './DemoCaption';
import { useDemoInterrupt } from './useDemoInterrupt';
import { useDemoPlayback, useDemoScript, type DemoPlayback } from './useDemoPlayback';

const DemoContext = createContext<DemoPlayback | null>(null);

const noop = () => undefined;

const DETACHED: DemoPlayback = {
  script: null,
  active: false,
  playing: false,
  frame: null,
  frameIndex: 0,
  start: noop,
  resume: noop,
  pause: noop,
  stop: noop
};

const isDemoControl = (target: EventTarget | null): boolean =>
  target instanceof Element && target.closest('[data-demo-control]') !== null;

export const DemoProvider = ({ children }: { children: ReactNode }) => {
  const { timeline, trace } = useTimeline();
  const document_ = useDataset('demoScript');
  const script = useDemoScript(
    document_.status === 'ready' ? document_.data : null,
    timeline.status === 'ready' ? timeline.data : null,
    trace.status === 'ready' ? trace.data : null
  );
  const playback = useDemoPlayback(script);
  const { active, playing, pause } = playback;

  const onInterrupt = useCallback(() => {
    if (playing) {
      pause();
    }
  }, [playing, pause]);

  useDemoInterrupt(active && playing, onInterrupt, isDemoControl);

  return <DemoContext.Provider value={playback}>{children}</DemoContext.Provider>;
};

export const useDemo = (): DemoPlayback => useContext(DemoContext) ?? DETACHED;

export const DemoStage = () => {
  const { script, active, frame } = useDemo();
  const ready = useMemo(
    () => active && script !== null && script.frames.length > 0 && frame !== null,
    [active, script, frame]
  );
  if (!ready || script === null || frame === null) {
    return null;
  }
  return <DemoCaption frame={frame} script={script} />;
};
