import { useEffect, useRef } from 'react';
import type { TimelineStep } from '../api/types';

const EDITABLE = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

export const isEditableTarget = (target: EventTarget | null): boolean => {
  if (target === null || !(target instanceof HTMLElement)) {
    return false;
  }
  return EDITABLE.has(target.tagName) || target.isContentEditable === true;
};

export const isInsideScroller = (target: EventTarget | null): boolean => {
  let node = target instanceof HTMLElement ? target : null;
  while (node !== null) {
    if (node.scrollHeight > node.clientHeight + 1) {
      const overflow = getComputedStyle(node).overflowY;
      if (overflow === 'auto' || overflow === 'scroll') {
        return true;
      }
    }
    node = node.parentElement;
  }
  return false;
};

const yearOf = (step: TimelineStep): number => Number(step.date.slice(0, 4));

export const stepForYearShift = (
  steps: TimelineStep[],
  stepIndex: number,
  direction: number
): number => {
  if (steps.length === 0) {
    return stepIndex;
  }
  const clamped = Math.min(Math.max(stepIndex, 0), steps.length - 1);
  const current = yearOf(steps[clamped]);
  if (!Number.isFinite(current)) {
    return clamped;
  }
  const target = current + direction;
  if (direction > 0) {
    for (let index = clamped + 1; index < steps.length; index += 1) {
      if (yearOf(steps[index]) >= target) {
        return index;
      }
    }
    return steps.length - 1;
  }
  let first = clamped;
  for (let index = clamped; index >= 0; index -= 1) {
    const year = yearOf(steps[index]);
    if (year > target) {
      continue;
    }
    if (year < target) {
      break;
    }
    first = index;
  }
  if (first === clamped) {
    for (let index = clamped - 1; index >= 0; index -= 1) {
      if (yearOf(steps[index]) < current) {
        return index;
      }
    }
    return 0;
  }
  return first;
};

interface HotkeyHandlers {
  steps: TimelineStep[];
  stepIndex: number;
  enabled?: boolean;
  onStep: (delta: number) => void;
  onSelect: (index: number) => void;
  onTogglePlay: () => void;
}

export const useHotkeys = ({
  steps,
  stepIndex,
  enabled = true,
  onStep,
  onSelect,
  onTogglePlay
}: HotkeyHandlers): void => {
  const handlers = useRef({ steps, stepIndex, onStep, onSelect, onTogglePlay });
  handlers.current = { steps, stepIndex, onStep, onSelect, onTogglePlay };

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (isEditableTarget(event.target)) {
        return;
      }
      const state = handlers.current;
      if (event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault();
        state.onTogglePlay();
        return;
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        state.onStep(-1);
        return;
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        state.onStep(1);
        return;
      }
      if (event.key === 'Home' || event.key === 'End') {
        if (isInsideScroller(event.target)) {
          return;
        }
        event.preventDefault();
        state.onSelect(event.key === 'Home' ? 0 : Math.max(state.steps.length - 1, 0));
        return;
      }
      if (event.key === '[' || event.key === ']') {
        event.preventDefault();
        const direction = event.key === ']' ? 1 : -1;
        state.onSelect(stepForYearShift(state.steps, state.stepIndex, direction));
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled]);
};
