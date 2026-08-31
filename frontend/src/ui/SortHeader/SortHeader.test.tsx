import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SortHeader, type SortDirection } from './SortHeader';

const renderHeader = (
  overrides: Partial<{
    active: boolean;
    dir: SortDirection;
    numericClass: string;
    onSort: () => void;
  }> = {}
) => {
  const onSort = overrides.onSort ?? vi.fn();
  const result = render(
    <table>
      <thead>
        <tr>
          <SortHeader
            prefix="wells"
            label="Дебит"
            active={overrides.active ?? false}
            dir={overrides.dir ?? 'asc'}
            title="Сортировать по дебиту"
            numericClass={overrides.numericClass}
            onSort={onSort}
          />
        </tr>
      </thead>
    </table>
  );
  return { ...result, onSort };
};

describe('SortHeader', () => {
  it('calls onSort when the header button is clicked', () => {
    const onSort = vi.fn();
    renderHeader({ onSort });

    fireEvent.click(screen.getByRole('button', { name: 'Дебит' }));

    expect(onSort).toHaveBeenCalledTimes(1);
  });

  it('reports no sort direction to assistive tech while inactive', () => {
    renderHeader({ active: false });

    expect(screen.getByRole('columnheader').getAttribute('aria-sort')).toBe('none');
    expect(screen.getByRole('button', { name: 'Дебит' }).dataset.active).toBe('false');
  });

  it('marks the active ascending column as ascending', () => {
    renderHeader({ active: true, dir: 'asc' });

    expect(screen.getByRole('columnheader').getAttribute('aria-sort')).toBe('ascending');
    expect(screen.getByRole('button', { name: 'Дебит' }).dataset.active).toBe('true');
  });

  it('marks the active descending column as descending', () => {
    renderHeader({ active: true, dir: 'desc' });

    expect(screen.getByRole('columnheader').getAttribute('aria-sort')).toBe('descending');
  });

  it('points the arrow up only for the active ascending column', () => {
    const { container, rerender } = renderHeader({ active: true, dir: 'asc' });
    const arrow = () => container.querySelector('.wells-sort-arrow') as HTMLElement;

    expect(arrow().textContent).toBe('↑');

    rerender(
      <table>
        <thead>
          <tr>
            <SortHeader
              prefix="wells"
              label="Дебит"
              active
              dir="desc"
              title="Сортировать по дебиту"
              onSort={vi.fn()}
            />
          </tr>
        </thead>
      </table>
    );

    expect(arrow().textContent).toBe('↓');
  });

  it('keeps the resting arrow down while the column is inactive', () => {
    const { container } = renderHeader({ active: false, dir: 'asc' });

    expect((container.querySelector('.wells-sort-arrow') as HTMLElement).textContent).toBe('↓');
  });

  it('places the arrow after the label in document order', () => {
    const { container } = renderHeader({ active: true, dir: 'asc' });
    const spans = [...(container.querySelector('button')?.children ?? [])];

    expect(spans).toHaveLength(2);
    expect(spans[0].textContent).toBe('Дебит');
    expect(spans[1].className).toBe('wells-sort-arrow');
  });

  it('hides the decorative arrow from the accessible name', () => {
    const { container } = renderHeader({ active: true, dir: 'asc' });

    expect(container.querySelector('.wells-sort-arrow')?.getAttribute('aria-hidden')).toBe('true');
    expect(screen.getByRole('button', { name: 'Дебит' })).not.toBeNull();
  });

  it('exposes the explanatory title on the button and applies the numeric class to the cell', () => {
    renderHeader({ numericClass: 'wells-numeric' });

    expect(screen.getByRole('button', { name: 'Дебит' }).getAttribute('title')).toBe(
      'Сортировать по дебиту'
    );
    expect(screen.getByRole('columnheader').className).toBe('wells-numeric');
    expect(screen.getByRole('columnheader').getAttribute('scope')).toBe('col');
  });
});
