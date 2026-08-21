import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
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
}

export const SegmentedControl = <Value,>({
  options,
  active,
  label,
  onSelect
}: SegmentedControlProps<Value>) => {
  const refs = useRef<Map<string, HTMLButtonElement | null>>(new Map());
  const [thumb, setThumb] = useState<CSSProperties>({ opacity: 0 });
  const activeKey = String(active);

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
    <div className="segmented" role="group" aria-label={label}>
      <span className="segmented-thumb" style={thumb} aria-hidden="true" />
      {options.map((option) => {
        const key = String(option.value);
        const disabled = option.disabled === true;
        return (
          <button
            key={key}
            type="button"
            className="segmented-button"
            aria-pressed={key === activeKey}
            aria-disabled={disabled}
            title={disabled ? option.disabledReason : undefined}
            disabled={disabled}
            ref={(node) => {
              refs.current.set(key, node);
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
