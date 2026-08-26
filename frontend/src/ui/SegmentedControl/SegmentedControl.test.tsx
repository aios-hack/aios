import { render, screen, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { SegmentedControl, type SegmentedOption } from './SegmentedControl';

type View = 'a' | 'b' | 'c';

const OPTIONS: SegmentedOption<View>[] = [
  { value: 'a', label: 'A' },
  { value: 'b', label: 'B' },
  { value: 'c', label: 'C' }
];

const Controlled = ({ onSelect }: { onSelect: (value: View) => void }) => {
  const [active, setActive] = useState<View>('a');
  return (
    <SegmentedControl
      options={OPTIONS}
      active={active}
      label="views"
      onSelect={(value) => {
        setActive(value);
        onSelect(value);
      }}
    />
  );
};

describe('SegmentedControl', () => {
  it('changes the view immediately on ArrowRight without Enter', () => {
    const onSelect = vi.fn();
    render(<Controlled onSelect={onSelect} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(onSelect).toHaveBeenCalledWith('b');
    expect(screen.getByRole('tab', { name: 'B' }).getAttribute('aria-selected')).toBe('true');
  });

  it('leaves a correct final view after ten rapid ArrowRight presses', () => {
    const onSelect = vi.fn();
    render(<Controlled onSelect={onSelect} />);
    const tablist = screen.getByRole('tablist');
    for (let i = 0; i < 10; i += 1) {
      fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    }
    expect(screen.getByRole('tab', { name: 'B' }).getAttribute('aria-selected')).toBe('true');
  });

  it('exposes a single tab stop into the group', () => {
    render(<Controlled onSelect={vi.fn()} />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs.filter((tab) => tab.tabIndex === 0).length).toBe(1);
  });

  it('skips a disabled segment when moving with ArrowRight', () => {
    const options: SegmentedOption<View>[] = [
      { value: 'a', label: 'A' },
      { value: 'b', label: 'B', disabled: true },
      { value: 'c', label: 'C' }
    ];
    const onSelect = vi.fn();
    render(<SegmentedControl options={options} active="a" label="views" onSelect={onSelect} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(onSelect).toHaveBeenCalledWith('c');
  });

  it('styles the selected tab off the real aria-selected attribute, not a stale aria-pressed rule', () => {
    const css = readFileSync(join(__dirname, 'SegmentedControl.css'), 'utf-8');
    expect(css).toContain("[aria-selected='true']");
    expect(css).not.toContain('aria-pressed');
    const activeRule = css.match(/\.segmented-button\[aria-selected='true'\]\s*\{([^}]*)\}/);
    expect(activeRule).not.toBeNull();
    expect(activeRule?.[1]).toContain('--color-accent-contrast');
  });
});
