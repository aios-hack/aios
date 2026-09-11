import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';

export type RovingOrientation = 'vertical' | 'horizontal';
export type RovingActivation = 'manual' | 'automatic';

interface UseRovingTabsOptions {
  count: number;
  activeIndex: number;
  orientation: RovingOrientation;
  activation: RovingActivation;
  isDisabled?: (index: number) => boolean;
  onActivate: (index: number) => void;
}

interface RovingTabProps {
  tabIndex: number;
  onFocus: () => void;
  ref: (node: HTMLElement | null) => void;
}

interface UseRovingTabsResult {
  focusIndex: number;
  onKeyDown: (event: KeyboardEvent) => void;
  getTabProps: (index: number) => RovingTabProps;
}

export const useRovingTabs = ({
  count,
  activeIndex,
  orientation,
  activation,
  isDisabled,
  onActivate
}: UseRovingTabsOptions): UseRovingTabsResult => {
  const [focusIndex, setFocusIndex] = useState(activeIndex);
  const focusIndexRef = useRef(focusIndex);
  focusIndexRef.current = focusIndex;
  const nodes = useRef<Map<number, HTMLElement | null>>(new Map());
  const shouldFocus = useRef(false);

  useEffect(() => {
    if (!shouldFocus.current) {
      return;
    }
    shouldFocus.current = false;
    nodes.current.get(focusIndex)?.focus();
  }, [focusIndex]);

  useEffect(() => {
    if (activation === 'automatic') {
      setFocusIndex(activeIndex);
    }
  }, [activeIndex, activation]);

  const disabled = useCallback(
    (index: number) => (isDisabled ? isDisabled(index) : false),
    [isDisabled]
  );

  const findNextEnabled = useCallback(
    (from: number, direction: number): number => {
      if (count === 0) {
        return from;
      }
      let index = from;
      for (let step = 0; step < count; step += 1) {
        index = (index + direction + count) % count;
        if (!disabled(index)) {
          return index;
        }
      }
      return from;
    },
    [count, disabled]
  );

  const findFirstEnabled = useCallback((): number => {
    for (let index = 0; index < count; index += 1) {
      if (!disabled(index)) {
        return index;
      }
    }
    return 0;
  }, [count, disabled]);

  const findLastEnabled = useCallback((): number => {
    for (let index = count - 1; index >= 0; index -= 1) {
      if (!disabled(index)) {
        return index;
      }
    }
    return count - 1;
  }, [count, disabled]);

  const moveFocus = useCallback(
    (nextIndex: number) => {
      shouldFocus.current = true;
      setFocusIndex(nextIndex);
      if (activation === 'automatic' && !disabled(nextIndex)) {
        onActivate(nextIndex);
      }
    },
    [activation, disabled, onActivate]
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const forwardKey = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
      const backwardKey = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
      const current = focusIndexRef.current;

      if (event.key === forwardKey) {
        if (activation === 'manual') {
          event.preventDefault();
        }
        moveFocus(findNextEnabled(current, 1));
        return;
      }
      if (event.key === backwardKey) {
        if (activation === 'manual') {
          event.preventDefault();
        }
        moveFocus(findNextEnabled(current, -1));
        return;
      }
      if (event.key === 'Home') {
        if (activation === 'manual') {
          event.preventDefault();
        }
        moveFocus(findFirstEnabled());
        return;
      }
      if (event.key === 'End') {
        if (activation === 'manual') {
          event.preventDefault();
        }
        moveFocus(findLastEnabled());
        return;
      }
      if (event.key === 'Enter' || event.key === ' ') {
        if (activation === 'manual' && !disabled(current)) {
          event.preventDefault();
          onActivate(current);
        }
      }
    },
    [orientation, moveFocus, findNextEnabled, findFirstEnabled, findLastEnabled, activation, disabled, onActivate]
  );

  const getTabProps = useCallback(
    (index: number): RovingTabProps => ({
      tabIndex: index === focusIndex ? 0 : -1,
      onFocus: () => setFocusIndex(index),
      ref: (node: HTMLElement | null) => {
        nodes.current.set(index, node);
      }
    }),
    [focusIndex]
  );

  return { focusIndex, onKeyDown, getTabProps };
};
