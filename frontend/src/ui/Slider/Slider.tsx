import type { CSSProperties } from 'react';
import './Slider.css';

interface SliderProps {
  id?: string;
  className?: string;
  min: number;
  max: number;
  step: number;
  value: number;
  ariaLabel?: string;
  guide?: string;
  onChange: (value: number) => void;
}

export const Slider = ({
  id,
  className,
  min,
  max,
  step,
  value,
  ariaLabel,
  guide,
  onChange
}: SliderProps) => {
  const span = max - min;
  const filled = span > 0 ? (value - min) / span : 0;
  const style = {
    '--slider-scale': filled,
    '--slider-offset': `${filled * 100}`
  } as CSSProperties;

  return (
    <span
      className={className ? `slider ${className}` : 'slider'}
      data-guide={guide}
      style={style}
    >
      <span className="slider-rail" aria-hidden="true">
        <span className="slider-fill" />
      </span>
      <input
        id={id}
        className="slider-input"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-label={ariaLabel}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <span className="slider-thumb" aria-hidden="true" />
    </span>
  );
};
