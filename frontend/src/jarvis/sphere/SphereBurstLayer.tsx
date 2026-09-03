import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { useJarvis } from '../JarvisContext';
import { LAUNCHER_SLOT_ID } from '../JarvisLauncher';
import { STAGE_SLOT_ID } from '../scene/stageSlot';
import { EnergySphere } from './EnergySphere';
import {
  burstDurationOf,
  burstFrameAt,
  burstModeOf,
  burstStyle,
  type BurstFrame,
  type BurstMode
} from './sphereBurst';
import { readSlot, type SlotRect } from './sphereSlot';
import './SphereBurstLayer.css';

const REST: BurstFrame = { scale: 1, opacity: 1, burst: 0 };
const GONE: BurstFrame = { scale: 1, opacity: 0, burst: 0 };

interface Play {
  mode: BurstMode;
  slot: SlotRect;
  frame: BurstFrame;
}

const slotOf = (id: string): SlotRect | null =>
  readSlot(typeof document === 'undefined' ? null : document.getElementById(id));

const boxStyle = (slot: SlotRect): CSSProperties => ({
  left: `${slot.left}px`,
  top: `${slot.top}px`,
  width: `${slot.width}px`,
  height: `${slot.height}px`
});

export const SphereBurstLayer = () => {
  const { transition, sphereState, audioLevel, crossfade } = useJarvis();
  const [play, setPlay] = useState<Play | null>(null);
  const raf = useRef(0);
  const home = useRef<SlotRect | null>(null);

  const mode = burstModeOf(transition.phase);
  const closing = transition.direction === 'closing';
  const settled = transition.phase === 'open';
  const shut = transition.phase === 'closed';

  useEffect(() => {
    if (!shut) {
      return;
    }
    const capture = () => {
      const slot = slotOf(LAUNCHER_SLOT_ID);
      if (slot !== null) {
        home.current = slot;
      }
    };
    capture();
    window.addEventListener('resize', capture);
    return () => window.removeEventListener('resize', capture);
  }, [shut]);

  useEffect(() => {
    if (mode === 'none') {
      return;
    }
    const atLauncher = mode === 'collapse' ? !closing : closing;
    const slot = atLauncher ? (home.current ?? slotOf(LAUNCHER_SLOT_ID)) : slotOf(STAGE_SLOT_ID);
    if (slot === null) {
      return;
    }
    if (crossfade) {
      setPlay({ mode, slot, frame: mode === 'collapse' ? GONE : REST });
      return;
    }
    cancelAnimationFrame(raf.current);
    const duration = burstDurationOf(mode);
    const start = performance.now();
    setPlay({ mode, slot, frame: burstFrameAt(mode, 0) });
    const tick = (now: number) => {
      const elapsed = now - start;
      setPlay({ mode, slot, frame: burstFrameAt(mode, elapsed) });
      if (elapsed < duration) {
        raf.current = requestAnimationFrame(tick);
      }
    };
    raf.current = requestAnimationFrame(tick);
  }, [mode, closing, crossfade]);

  useEffect(() => {
    if (!settled) {
      return;
    }
    const sync = () => {
      const slot = slotOf(STAGE_SLOT_ID);
      if (slot !== null) {
        setPlay({ mode: 'none', slot, frame: REST });
      }
    };
    const timer = window.setTimeout(sync, crossfade ? 0 : burstDurationOf('materialize'));
    window.addEventListener('resize', sync);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('resize', sync);
    };
  }, [settled, crossfade]);

  useEffect(() => {
    if (shut) {
      cancelAnimationFrame(raf.current);
      setPlay(null);
    }
  }, [shut]);

  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  if (play === null) {
    return null;
  }

  return (
    <span
      className="jarvis-sphere-burst"
      data-mode={play.mode}
      style={{ ...boxStyle(play.slot), ...burstStyle(play.frame) }}
    >
      <EnergySphere state={sphereState} audio={audioLevel} burst={play.frame.burst} />
    </span>
  );
};
