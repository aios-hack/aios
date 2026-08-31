import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { Slider } from './Slider';

const LABEL = 'Шаг управления';

const Controlled = ({
  onChange,
  min = 0,
  max = 10,
  step = 1,
  initial = 4
}: {
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  initial?: number;
}) => {
  const [value, setValue] = useState(initial);
  return (
    <Slider
      min={min}
      max={max}
      step={step}
      value={value}
      ariaLabel={LABEL}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
};

const slider = () => screen.getByRole('slider', { name: LABEL }) as HTMLInputElement;

describe('Slider', () => {
  it('exposes a range input with an accessible name', () => {
    render(<Controlled onChange={vi.fn()} />);

    expect(slider().type).toBe('range');
    expect(slider().getAttribute('aria-label')).toBe(LABEL);
  });

  it('publishes its bounds and granularity to assistive tech', () => {
    render(<Controlled onChange={vi.fn()} min={2} max={20} step={2} initial={6} />);

    expect(slider().min).toBe('2');
    expect(slider().max).toBe('20');
    expect(slider().step).toBe('2');
    expect(slider().value).toBe('6');
  });

  it('calls onChange with a number, not a string', () => {
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);

    fireEvent.change(slider(), { target: { value: '7' } });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(7);
    expect(typeof onChange.mock.calls[0][0]).toBe('number');
  });

  it('reflects the new value after a change', () => {
    render(<Controlled onChange={vi.fn()} />);

    fireEvent.change(slider(), { target: { value: '9' } });

    expect(slider().value).toBe('9');
  });

  it('reports a one-step increase from the keyboard as a committed value', () => {
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} initial={4} />);

    slider().focus();
    slider().stepUp();
    fireEvent.change(slider());

    expect(onChange).toHaveBeenCalledWith(5);
    expect(slider().value).toBe('5');
  });

  it('reports a one-step decrease from the keyboard as a committed value', () => {
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} initial={4} />);

    slider().focus();
    slider().stepDown();
    fireEvent.change(slider());

    expect(onChange).toHaveBeenCalledWith(3);
    expect(slider().value).toBe('3');
  });

  it('honours a non-unit step when stepping', () => {
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} min={0} max={100} step={25} initial={25} />);

    slider().stepUp();
    fireEvent.change(slider());

    expect(onChange).toHaveBeenCalledWith(50);
    expect(slider().value).toBe('50');
  });

  it('does not step past the maximum', () => {
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} min={0} max={5} step={1} initial={5} />);

    slider().stepUp();
    fireEvent.change(slider());

    expect(slider().value).toBe('5');
  });

  it('is reachable by the keyboard', () => {
    render(<Controlled onChange={vi.fn()} />);

    slider().focus();

    expect(document.activeElement).toBe(slider());
    expect(slider().tabIndex).toBe(0);
  });

  it('clamps a value below the minimum to the minimum', () => {
    render(<Controlled onChange={vi.fn()} min={5} max={10} initial={5} />);

    fireEvent.change(slider(), { target: { value: '1' } });

    expect(slider().value).toBe('5');
  });

  it('clamps a value above the maximum to the maximum', () => {
    render(<Controlled onChange={vi.fn()} min={0} max={10} initial={5} />);

    fireEvent.change(slider(), { target: { value: '99' } });

    expect(slider().value).toBe('10');
  });

  it('drives the fill from the fraction of the range that is covered', () => {
    const { container } = render(
      <Slider min={0} max={10} step={1} value={3} ariaLabel={LABEL} onChange={vi.fn()} />
    );

    expect((container.firstChild as HTMLElement).style.getPropertyValue('--slider-scale')).toBe(
      '0.3'
    );
  });

  it('does not divide by zero when the range is degenerate', () => {
    const { container } = render(
      <Slider min={5} max={5} step={1} value={5} ariaLabel={LABEL} onChange={vi.fn()} />
    );

    expect((container.firstChild as HTMLElement).style.getPropertyValue('--slider-scale')).toBe(
      '0'
    );
  });

  it('appends an extra class and forwards the id without losing its own class', () => {
    const { container } = render(
      <Slider
        id="step-slider"
        className="timeline-slider"
        min={0}
        max={10}
        step={1}
        value={5}
        ariaLabel={LABEL}
        onChange={vi.fn()}
      />
    );

    expect((container.firstChild as HTMLElement).className).toBe('slider timeline-slider');
    expect(slider().id).toBe('step-slider');
  });

  it('hides the decorative rail and thumb from assistive tech', () => {
    const { container } = render(
      <Slider min={0} max={10} step={1} value={5} ariaLabel={LABEL} onChange={vi.fn()} />
    );

    expect(container.querySelector('.slider-rail')?.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelector('.slider-thumb')?.getAttribute('aria-hidden')).toBe('true');
    expect(screen.getAllByRole('slider')).toHaveLength(1);
  });
});
