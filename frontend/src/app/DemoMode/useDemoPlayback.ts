import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DemoScriptFile, TimelineFile, TraceFile } from '../../api/types';
import { useConsole } from '../../state/ConsoleContext';
import { useTimeline } from '../../state/TimelineContext';
import { prefersReducedMotion } from '../../views/FieldProjection/useProjection';
import { playIntervalMs, PLAY_SPEEDS } from '../useStepPlayback';
import { reportSkipped, resolveScript, type DemoScript, type ResolvedFrame } from './frames';
import { workspaceViewOfScene } from './scenes';

export const DEMO_TRAVEL_SPEED = PLAY_SPEEDS[PLAY_SPEEDS.length - 1];

export interface DemoPlayback {
  script: DemoScript | null;
  active: boolean;
  playing: boolean;
  frame: ResolvedFrame | null;
  frameIndex: number;
  start: () => void;
  resume: () => void;
  pause: () => void;
  stop: () => void;
}

const emptyScript = (): DemoScript => ({ frames: [], skipped: [], totalMs: 0 });

export const useDemoScript = (
  script: DemoScriptFile | null,
  timeline: TimelineFile | null,
  trace: TraceFile | null
): DemoScript | null =>
  useMemo(() => {
    if (script === null || timeline === null || trace === null) {
      return null;
    }
    const resolved = resolveScript(script, timeline, trace);
    reportSkipped(resolved.skipped);
    return resolved.frames.length === 0 ? emptyScript() : resolved;
  }, [script, timeline, trace]);

export const useDemoPlayback = (script: DemoScript | null): DemoPlayback => {
  const { setStepIndex, selectWell } = useTimeline();
  const { setWorkspace, setView, requestMorph } = useConsole();
  const [active, setActive] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [frameIndex, setFrameIndex] = useState(0);
  const timerRef = useRef<number | null>(null);
  const travelRef = useRef<number | null>(null);

  const clearTimers = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (travelRef.current !== null) {
      window.clearInterval(travelRef.current);
      travelRef.current = null;
    }
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const frames = script?.frames ?? [];
  const frame = frames.length === 0 ? null : (frames[Math.min(frameIndex, frames.length - 1)] ?? null);

  const morphRef = useRef(requestMorph);
  morphRef.current = requestMorph;

  const travelTo = useCallback(
    (target: number) => {
      if (travelRef.current !== null) {
        window.clearInterval(travelRef.current);
        travelRef.current = null;
      }
      if (prefersReducedMotion()) {
        setStepIndex(target);
        return;
      }
      travelRef.current = window.setInterval(() => {
        setStepIndex((current) => {
          if (current === target) {
            return current;
          }
          const next = current + Math.sign(target - current);
          if (next === target && travelRef.current !== null) {
            window.clearInterval(travelRef.current);
            travelRef.current = null;
          }
          return next;
        });
      }, playIntervalMs(DEMO_TRAVEL_SPEED));
    },
    [setStepIndex]
  );

  useEffect(() => {
    if (!active || !playing || frame === null) {
      return;
    }
    const target = workspaceViewOfScene(frame.scene);
    setWorkspace(target.workspace);
    setView(target.view);
    selectWell(frame.well);
    travelTo(frame.step);
    const morphTo = frame.morphTo;
    const morphTimer =
      morphTo === null ? null : window.setTimeout(() => morphRef.current(morphTo), 0);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setFrameIndex((current) => {
        if (current >= frames.length - 1) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, frame.holdMs);
    return () => {
      if (morphTimer !== null) {
        window.clearTimeout(morphTimer);
      }
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [active, playing, frame, frames.length, setWorkspace, setView, selectWell, travelTo]);

  const pause = useCallback(() => {
    clearTimers();
    setPlaying(false);
  }, [clearTimers]);

  const start = useCallback(() => {
    clearTimers();
    setFrameIndex(0);
    setActive(true);
    setPlaying(true);
  }, [clearTimers]);

  const resume = useCallback(() => {
    setActive(true);
    setPlaying(true);
  }, []);

  const stop = useCallback(() => {
    clearTimers();
    setActive(false);
    setPlaying(false);
    setFrameIndex(0);
  }, [clearTimers]);

  return { script, active, playing, frame, frameIndex, start, resume, pause, stop };
};
