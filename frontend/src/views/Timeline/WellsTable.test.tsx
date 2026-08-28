import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fireEvent, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { TimelineWellRow } from '../../api/types';
import { I18nProvider } from '../../i18n/I18nContext';
import { SORT_KEYS } from './sorting';
import { WellsTable } from './WellsTable';

const WELL_COUNT = 20;

const makeWell = (index: number): TimelineWellRow => ({
  well: `W${String(index + 1).padStart(2, '0')}`,
  availability: index === WELL_COUNT - 1 ? 'NOT_COMMISSIONED' : 'AVAILABLE',
  role: index % 3 === 0 ? 'INJ' : 'PROD',
  operating_status: index % 5 === 0 ? 'SHUT' : 'OPEN',
  setpoint: 100 + index,
  liquid_rate: 40 + index,
  injection_rate: 120 + index,
  bhp: 90 + index,
  watercut: index % 4 === 0 ? null : Math.min(0.05 * index, 1),
  fact_to_target: 0.4 + index / 100,
  cumulative_liquid: 1000 * (index + 1)
});

const wells = Array.from({ length: WELL_COUNT }, (_, index) => makeWell(index));

const withProviders = (node: ReactNode) => <I18nProvider>{node}</I18nProvider>;

const bodyRows = (container: HTMLElement): HTMLTableRowElement[] =>
  Array.from(container.querySelectorAll<HTMLTableRowElement>('tbody tr'));

describe('wells table reveal order', () => {
  it('numbers the rows in the order they are rendered so the stagger follows the sort', () => {
    const { container } = render(
      withProviders(<WellsTable wells={wells} selectedWell={null} onSelectWell={() => {}} />)
    );
    const rows = bodyRows(container);
    expect(rows).toHaveLength(WELL_COUNT);
    expect(rows[0].dataset.wellId).toBe('W01');
    expect(rows[0].dataset.ordinal).toBe('0');
    expect(rows[3].dataset.ordinal).toBe('3');
  });

  it('caps the reveal offset so a long roster does not wait on a growing delay', () => {
    const { container } = render(
      withProviders(<WellsTable wells={wells} selectedWell={null} onSelectWell={() => {}} />)
    );
    const ordinals = bodyRows(container).map((row) => Number(row.dataset.ordinal));
    expect(Math.max(...ordinals)).toBeLessThan(WELL_COUNT - 1);
    expect(ordinals[ordinals.length - 1]).toBe(Math.max(...ordinals));
    expect(ordinals).toEqual([...ordinals].sort((a, b) => a - b));
  });

  it('renumbers the rows when the sort changes so the first row is always index zero', () => {
    const { container } = render(
      withProviders(<WellsTable wells={wells} selectedWell={null} onSelectWell={() => {}} />)
    );
    const firstBefore = bodyRows(container)[0].dataset.wellId;
    const sortButtons = container.querySelectorAll<HTMLButtonElement>('.timeline-sort-button');
    expect(sortButtons.length).toBe(SORT_KEYS.length);
    fireEvent.click(sortButtons[SORT_KEYS.indexOf('bhp')]);
    const rows = bodyRows(container);
    expect(rows[0].dataset.ordinal).toBe('0');
    expect(rows[rows.length - 1].dataset.ordinal).toBe(String(Math.min(WELL_COUNT - 1, 12)));
    expect(rows[0].dataset.wellId).not.toBe(firstBefore);
  });

  it('reports the clicked well to the caller rather than swallowing the row click', () => {
    const onSelectWell = vi.fn();
    const { container } = render(
      withProviders(<WellsTable wells={wells} selectedWell={null} onSelectWell={onSelectWell} />)
    );
    fireEvent.click(bodyRows(container)[2]);
    expect(onSelectWell).toHaveBeenCalledWith('W03');
  });
});

describe('the wells table matches the console table pattern', () => {
  const css = readFileSync(
    join(process.cwd(), 'src', 'views', 'Timeline', 'WellsTable.css'),
    'utf-8'
  );

  it('names the table for a reader who cannot see the heading above it', () => {
    const { container } = render(
      withProviders(<WellsTable wells={wells} selectedWell={null} onSelectWell={() => undefined} />)
    );
    const caption = container.querySelector('caption');

    expect(caption).not.toBeNull();
    expect((caption?.textContent ?? '').length).toBeGreaterThan(10);
  });

  it('keeps the caption available to assistive tech without showing it twice', () => {
    const block = css.match(/\.timeline-caption\s*\{[^}]*\}/)?.[0] ?? '';
    expect(block).toContain('clip-path');
    expect(block).not.toContain('display: none');
  });

  it('pins the header so the columns stay named down a long table', () => {
    const block = css.match(/\.timeline-table thead th\s*\{[^}]*\}/)?.[0] ?? '';
    expect(block).toContain('position: sticky');
    expect(block).toContain('background:');
  });

  it('gives the sort control a target taller than its text', () => {
    const block = css.match(/\.timeline-sort-button\s*\{[^}]*\}/)?.[0] ?? '';
    expect(block).toContain('min-height');
    expect(block).not.toMatch(/padding:\s*0;/);
  });

  it('lets the well link fill its cell instead of sitting as a bare glyph', () => {
    const block = css.match(/\.timeline-well-button\s*\{[^}]*\}/)?.[0] ?? '';
    expect(block).toContain('min-height');
    expect(block).toContain('width: 100%');
  });
});
