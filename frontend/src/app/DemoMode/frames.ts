import type {
  DemoEvent,
  DemoFrame,
  DemoScriptFile,
  TimelineFile,
  TimelineStep,
  TimelineWellRow,
  TraceFile
} from '../../api/types';
import { sceneModeOf, type SceneMode } from './scenes';

export interface ResolvedFrame {
  index: number;
  step: number;
  scene: SceneMode;
  well: string | null;
  event: DemoEvent | null;
  holdMs: number;
  morphTo: number | null;
  date: string;
  npvCumulative: number;
}

export interface SkippedFrame {
  index: number;
  reason: 'scene' | 'step' | 'event';
  detail: string;
}

export interface DemoScript {
  frames: ResolvedFrame[];
  skipped: SkippedFrame[];
  totalMs: number;
}

const rowOf = (step: TimelineStep, well: string): TimelineWellRow | null =>
  step.wells.find((row) => row.well === well) ?? null;

const hasTrace = (trace: TraceFile, well: string, step: number, rule?: string): boolean => {
  const records = trace[well]?.[String(step)];
  if (records === undefined || records.length === 0) {
    return false;
  }
  return rule === undefined || records.some((record) => record.rule === rule);
};

const changed = (
  steps: TimelineStep[],
  stepIndex: number,
  well: string,
  read: (row: TimelineWellRow) => string,
  to: string
): boolean => {
  const current = rowOf(steps[stepIndex], well);
  if (current === null || read(current) !== to) {
    return false;
  }
  if (stepIndex === 0) {
    return false;
  }
  const previous = rowOf(steps[stepIndex - 1], well);
  return previous !== null && read(previous) !== to;
};

export const confirmEvent = (
  event: DemoEvent,
  steps: TimelineStep[],
  trace: TraceFile,
  stepIndex: number
): boolean => {
  if (event.type === 'MORPH') {
    return true;
  }
  const well = event.well;
  if (well === undefined || rowOf(steps[stepIndex], well) === null) {
    return false;
  }
  if (event.type === 'RULE_FIRED') {
    return hasTrace(trace, well, stepIndex, event.rule);
  }
  if (event.type === 'COMMISSIONED') {
    return changed(steps, stepIndex, well, (row) => row.availability, 'AVAILABLE');
  }
  if (event.type === 'ROLE_CHANGE') {
    return changed(steps, stepIndex, well, (row) => row.role, 'INJ');
  }
  return changed(steps, stepIndex, well, (row) => row.operating_status, 'SHUT');
};

const resolveOne = (
  frame: DemoFrame,
  index: number,
  steps: TimelineStep[],
  trace: TraceFile
): ResolvedFrame | SkippedFrame => {
  const scene = sceneModeOf(frame.scene);
  if (scene === null) {
    return { index, reason: 'scene', detail: frame.scene };
  }
  if (!Number.isInteger(frame.step) || frame.step < 0 || frame.step >= steps.length) {
    return { index, reason: 'step', detail: String(frame.step) };
  }
  if (frame.event !== null && !confirmEvent(frame.event, steps, trace, frame.step)) {
    const well = frame.event.well ?? '';
    return { index, reason: 'event', detail: `${frame.event.type} ${well}`.trim() };
  }
  const step = steps[frame.step];
  return {
    index,
    step: frame.step,
    scene,
    well: frame.well,
    event: frame.event,
    holdMs: frame.hold_ms,
    morphTo: frame.t === undefined ? null : frame.t,
    date: step.date,
    npvCumulative: step.field.npv_cumulative
  };
};

const isSkipped = (value: ResolvedFrame | SkippedFrame): value is SkippedFrame =>
  'reason' in value;

export const resolveScript = (
  script: DemoScriptFile,
  timeline: TimelineFile,
  trace: TraceFile
): DemoScript => {
  const frames: ResolvedFrame[] = [];
  const skipped: SkippedFrame[] = [];
  script.frames.forEach((frame, index) => {
    const resolved = resolveOne(frame, index, timeline.steps, trace);
    if (isSkipped(resolved)) {
      skipped.push(resolved);
    } else {
      frames.push(resolved);
    }
  });
  const totalMs = frames.reduce((sum, frame) => sum + frame.holdMs, 0);
  return { frames, skipped, totalMs };
};

export const reportSkipped = (skipped: SkippedFrame[]): void => {
  for (const frame of skipped) {
    console.warn(`demo-script: frame ${frame.index} skipped (${frame.reason}: ${frame.detail})`);
  }
};
