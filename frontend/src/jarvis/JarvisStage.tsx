import { useEffect, useRef, type ReactNode } from 'react';
import { useJarvis } from './JarvisContext';
import { JarvisScreen } from './JarvisScreen';
import { SphereBurstLayer } from './sphere/SphereBurstLayer';
import {
  framesAreLagging,
  isMoving,
  type TransitionDirection,
  type TransitionPhase
} from './transition';
import './JarvisStage.css';

const FRAME_SAMPLES = 3;

const phaseOwner = (
  phase: TransitionPhase,
  direction: TransitionDirection,
  cube: HTMLElement
): Element | null => {
  if (phase === 'turning') {
    return cube;
  }
  const face = direction === 'closing' ? 'jarvis-face-screen' : 'jarvis-face-console';
  return cube.querySelector(`.${face} > .jarvis-face-scale`);
};

export const JarvisStage = ({ children }: { children: ReactNode }) => {
  const { transition, visible, moving, crossfade, requestCrossfade, settle } = useJarvis();
  const stageRef = useRef<HTMLDivElement>(null);
  const cubeRef = useRef<HTMLDivElement>(null);
  const samples = useRef<number[]>([]);

  useEffect(() => {
    if (transition.phase !== 'turning' || crossfade) {
      return;
    }
    samples.current = [];
    let last = performance.now();
    let raf = requestAnimationFrame(function tick(now: number) {
      samples.current.push(now - last);
      last = now;
      if (samples.current.length >= FRAME_SAMPLES) {
        if (framesAreLagging(samples.current)) {
          requestCrossfade();
        }
        return;
      }
      raf = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(raf);
  }, [transition.phase, crossfade, requestCrossfade]);

  useEffect(() => {
    const stage = stageRef.current;
    const cube = cubeRef.current;
    if (stage === null || cube === null || !isMoving(transition)) {
      return;
    }
    const onEnd = (event: TransitionEvent) => {
      if (event.propertyName !== 'transform') {
        return;
      }
      const owner = phaseOwner(transition.phase, transition.direction, cube);
      if (event.target !== owner) {
        return;
      }
      settle(transition.phase);
    };
    stage.addEventListener('transitionend', onEnd);
    return () => stage.removeEventListener('transitionend', onEnd);
  }, [transition, settle]);

  return (
    <div
      className="jarvis-stage"
      ref={stageRef}
      data-phase={transition.phase}
      data-direction={transition.direction}
      data-crossfade={crossfade ? 'true' : undefined}
    >
      <div className="jarvis-cube" ref={cubeRef}>
        <div className="jarvis-face jarvis-face-console" aria-hidden={transition.phase === 'open'}>
          <div className="jarvis-face-scale" inert={moving || transition.phase === 'open'}>
            {children}
          </div>
        </div>
        {visible ? (
          <div className="jarvis-face jarvis-face-screen">
            <div className="jarvis-face-scale" inert={moving}>
              <JarvisScreen />
            </div>
          </div>
        ) : null}
      </div>
      <SphereBurstLayer />
    </div>
  );
};
