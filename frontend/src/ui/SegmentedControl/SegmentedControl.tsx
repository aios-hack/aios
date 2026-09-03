import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { useRovingTabs } from '../shared/useRovingTabs';
import './SegmentedControl.css';

export interface SegmentedOption<Value> {
  value: Value;
  label: string;
  disabled?: boolean;
  disabledReason?: string;
}

interface SegmentedControlProps<Value> {
  options: readonly SegmentedOption<Value>[];
  active: Value;
  label: string;
  onSelect: (value: Value) => void;
  guide?: string;
}

export const SegmentedControl = <Value,>({
  options,
  active,
  label,
  onSelect,
  guide
}: SegmentedControlProps<Value>) => {
  const refs = useRef<Map<string, HTMLButtonElement | null>>(new Map());
  const [thumb, setThumb] = useState<CSSProperties>({ opacity: 0 });
  const activeKey = String(active);
  const activeIndex = options.findIndex((option) => String(option.value) === activeKey);

  const { focusIndex, onKeyDown, getTabProps } = useRovingTabs({
    count: options.length,
    activeIndex: activeIndex === -1 ? 0 : activeIndex,
    orientation: 'horizontal',
    activation: 'automatic',
    isDisabled: (index) => options[index]?.disabled === true,
    onActivate: (index) => {
      const option = options[index];
      if (option && !option.disabled) {
        onSelect(option.value);
      }
    }
  });

  useLayoutEffect(() => {
    const node = refs.current.get(activeKey);
    if (!node) {
      return;
    }
    setThumb({
      opacity: 1,
      width: `${node.offsetWidth}px`,
      transform: `translateX(${node.offsetLeft}px)`
    });
  }, [activeKey, options]);

  return (
    <div
      className="segmented"
      role="tablist"
      aria-label={label}
      data-guide={guide}
      onKeyDown={onKeyDown}
    >
      <span className="segmented-thumb" style={thumb} aria-hidden="true" />
      {options.map((option, index) => {
        const key = String(option.value);
        const disabled = option.disabled === true;
        const tabProps = getTabProps(index);
        return (
          <button
            key={key}
            type="button"
            role="tab"
            className="segmented-button"
            aria-selected={key === activeKey}
            aria-disabled={disabled}
            title={disabled ? option.disabledReason : undefined}
            disabled={disabled}
            tabIndex={tabProps.tabIndex}
            onFocus={tabProps.onFocus}
            data-focused={index === focusIndex}
            ref={(node) => {
              refs.current.set(key, node);
              tabProps.ref(node);
            }}
            onClick={() => {
              if (!disabled) {
                onSelect(option.value);
              }
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
};
