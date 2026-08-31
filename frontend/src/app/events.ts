import type { TimelineStep, TimelineWellRow } from '../api/types';

export type FieldEventType = 'COMMISSIONED' | 'ROLE_CHANGE' | 'SHUT';

export interface FieldEvent {
  step: number;
  well: string;
  type: FieldEventType;
}

export interface EventMark {
  step: number;
  types: FieldEventType[];
  count: number;
}

const rowIndex = (step: TimelineStep): Map<string, TimelineWellRow> =>
  new Map(step.wells.map((row) => [row.well, row]));

const diffRow = (
  previous: TimelineWellRow,
  current: TimelineWellRow
): FieldEventType | null => {
  if (previous.availability !== 'AVAILABLE' && current.availability === 'AVAILABLE') {
    return 'COMMISSIONED';
  }
  if (previous.role !== current.role && current.role === 'INJ') {
    return 'ROLE_CHANGE';
  }
  if (previous.operating_status !== 'SHUT' && current.operating_status === 'SHUT') {
    return 'SHUT';
  }
  return null;
};

export const fieldEvents = (steps: TimelineStep[]): FieldEvent[] => {
  const events: FieldEvent[] = [];
  for (let index = 1; index < steps.length; index += 1) {
    const previous = rowIndex(steps[index - 1]);
    for (const current of steps[index].wells) {
      const before = previous.get(current.well);
      if (before === undefined) {
        continue;
      }
      const type = diffRow(before, current);
      if (type !== null) {
        events.push({ step: index, well: current.well, type });
      }
    }
  }
  return events;
};

export const eventMarks = (events: FieldEvent[]): EventMark[] => {
  const byStep = new Map<number, FieldEventType[]>();
  for (const event of events) {
    const bucket = byStep.get(event.step);
    if (bucket === undefined) {
      byStep.set(event.step, [event.type]);
    } else if (!bucket.includes(event.type)) {
      bucket.push(event.type);
    }
  }
  const counts = new Map<number, number>();
  for (const event of events) {
    counts.set(event.step, (counts.get(event.step) ?? 0) + 1);
  }
  return [...byStep.entries()]
    .map(([step, types]) => ({ step, types, count: counts.get(step) ?? 0 }))
    .sort((a, b) => a.step - b.step);
};

export interface YearTick {
  step: number;
  year: string;
}

export const yearTicks = (steps: readonly TimelineStep[]): YearTick[] => {
  const ticks: YearTick[] = [];
  let last: string | null = null;
  for (let index = 0; index < steps.length; index += 1) {
    const year = steps[index].date.slice(0, 4);
    if (year.length === 4 && year !== last) {
      ticks.push({ step: index, year });
      last = year;
    }
  }
  return ticks;
};
