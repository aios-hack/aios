import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useRovingTabs } from './useRovingTabs';

interface HarnessProps {
  activeIndex: number;
  orientation: 'vertical' | 'horizontal';
  activation: 'manual' | 'automatic';
  onActivate: (index: number) => void;
  disabledIndexes?: number[];
}

const Harness = ({ activeIndex, orientation, activation, onActivate, disabledIndexes = [] }: HarnessProps) => {
  const { onKeyDown, getTabProps } = useRovingTabs({
    count: 3,
    activeIndex,
    orientation,
    activation,
    isDisabled: (index) => disabledIndexes.includes(index),
    onActivate
  });

  return (
    <div role="tablist" onKeyDown={onKeyDown}>
      {[0, 1, 2].map((index) => {
        const tabProps = getTabProps(index);
        return (
          <button
            key={index}
            role="tab"
            tabIndex={tabProps.tabIndex}
            onFocus={tabProps.onFocus}
            ref={tabProps.ref}
            data-testid={`tab-${index}`}
          >
            item {index}
          </button>
        );
      })}
    </div>
  );
};

describe('useRovingTabs', () => {
  it('moves focus forward and wraps to the first item at the end', () => {
    render(<Harness activeIndex={0} orientation="horizontal" activation="manual" onActivate={vi.fn()} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(screen.getByTestId('tab-0').tabIndex).toBe(0);
  });

  it('moves focus backward and wraps to the last item from the first', () => {
    render(<Harness activeIndex={0} orientation="horizontal" activation="manual" onActivate={vi.fn()} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowLeft' });
    expect(screen.getByTestId('tab-2').tabIndex).toBe(0);
  });

  it('Home and End jump to first and last', () => {
    render(<Harness activeIndex={0} orientation="horizontal" activation="manual" onActivate={vi.fn()} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'End' });
    expect(screen.getByTestId('tab-2').tabIndex).toBe(0);
    fireEvent.keyDown(tablist, { key: 'Home' });
    expect(screen.getByTestId('tab-0').tabIndex).toBe(0);
  });

  it('manual activation moves focus without calling onActivate on arrow keys', () => {
    const onActivate = vi.fn();
    render(<Harness activeIndex={0} orientation="horizontal" activation="manual" onActivate={onActivate} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(onActivate).not.toHaveBeenCalled();
    fireEvent.keyDown(tablist, { key: 'Enter' });
    expect(onActivate).toHaveBeenCalledWith(1);
  });

  it('automatic activation activates immediately on arrow keys', () => {
    const onActivate = vi.fn();
    render(<Harness activeIndex={0} orientation="horizontal" activation="automatic" onActivate={onActivate} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(onActivate).toHaveBeenCalledWith(1);
  });

  it('automatic activation does not preventDefault on arrows, so a global time hotkey still fires', () => {
    const onActivate = vi.fn();
    render(<Harness activeIndex={0} orientation="horizontal" activation="automatic" onActivate={onActivate} />);
    const tablist = screen.getByRole('tablist');
    const event = fireEvent.keyDown(tablist, { key: 'ArrowRight', cancelable: true });
    expect(event).toBe(true);
  });

  it('manual activation does preventDefault on arrows, since it owns the vertical axis', () => {
    const onActivate = vi.fn();
    render(<Harness activeIndex={0} orientation="vertical" activation="manual" onActivate={onActivate} />);
    const tablist = screen.getByRole('tablist');
    const event = fireEvent.keyDown(tablist, { key: 'ArrowDown', cancelable: true });
    expect(event).toBe(false);
  });

  it('skips disabled items while traversing', () => {
    const onActivate = vi.fn();
    render(
      <Harness
        activeIndex={0}
        orientation="horizontal"
        activation="automatic"
        onActivate={onActivate}
        disabledIndexes={[1]}
      />
    );
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(onActivate).toHaveBeenCalledWith(2);
  });

  it('uses vertical arrow keys when orientation is vertical', () => {
    const onActivate = vi.fn();
    render(<Harness activeIndex={0} orientation="vertical" activation="automatic" onActivate={onActivate} />);
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowRight' });
    expect(onActivate).not.toHaveBeenCalled();
    fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    expect(onActivate).toHaveBeenCalledWith(1);
  });

  it('moves the real DOM focus, not only the tabindex', async () => {
    render(
      <Harness activeIndex={0} orientation="vertical" activation="manual" onActivate={vi.fn()} />
    );
    const tabs = screen.getAllByRole('tab');
    tabs[0].focus();
    expect(document.activeElement).toBe(tabs[0]);
    fireEvent.keyDown(tabs[0], { key: 'ArrowDown' });
    await waitFor(() => expect(document.activeElement).toBe(tabs[1]));
    expect(tabs[1].tabIndex).toBe(0);
    expect(tabs[0].tabIndex).toBe(-1);
  });
});
