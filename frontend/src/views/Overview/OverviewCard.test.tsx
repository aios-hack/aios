import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactNode } from 'react';
import type { TimelineStep, TimelineWellRow } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { overviewMetrics } from './overviewMetrics';
import { OverviewCard } from './OverviewCard';

const STEP_COUNT = 6;

const wellRow = (index: number): TimelineWellRow => ({
  well: `P${index + 1}`,
  availability: 'AVAILABLE',
  role: index % 2 === 0 ? 'PROD' : 'INJ',
  operating_status: index === 1 ? 'SHUT' : 'OPEN',
  setpoint: 50 + index,
  liquid_rate: 40 + index,
  injection_rate: 20 + index,
  bhp: 90 + index,
  watercut: 0.2 + index / 20,
  fact_to_target: 0.8 + index / 50,
  cumulative_liquid: 100 * (index + 1)
});

const steps: TimelineStep[] = Array.from({ length: STEP_COUNT }, (_, k) => ({
  control_step: k,
  date: `${2007 + k}-01-01`,
  terminal: k === STEP_COUNT - 1,
  field: {
    production: 1000 + 50 * k,
    injection: 800 + 40 * k,
    compensation: 0.7 + k / 100,
    npv_cumulative: 5000 * (k + 1),
    active_wells: 4
  },
  wells: Array.from({ length: 4 }, (_, i) => wellRow(i))
}));

const band = { min: 0.72, max: 0.74 };

const withProviders = (node: ReactNode) => <I18nProvider>{node}</I18nProvider>;

const metrics = overviewMetrics(steps, STEP_COUNT - 1, band);

const renderCard = (index: number, featured = false) =>
  render(
    withProviders(
      <OverviewCard
        metric={metrics[index]}
        steps={steps}
        stepIndex={STEP_COUNT - 1}
        stroke="var(--color-oil)"
        format={(value) => (value === null ? '—' : String(Math.round(value)))}
        featured={featured}
        ordinal={index}
      />
    )
  );

describe('overview card reveal order', () => {
  it('carries its position so each card can be revealed after the one before it', () => {
    const { container } = renderCard(2);
    const card = container.querySelector<HTMLElement>('.overview-card');
    expect(card).not.toBeNull();
    expect(card!.dataset.ordinal).toBe('2');
    expect(card!.style.getPropertyValue('--overview-card-index')).toBe('2');
  });

  it('gives the first card a zero offset so the grid does not start with a pause', () => {
    const { container } = renderCard(0);
    const card = container.querySelector<HTMLElement>('.overview-card');
    expect(card!.style.getPropertyValue('--overview-card-index')).toBe('0');
  });

  it('keeps the reading and the band verdict on the card, not just the ordinal', () => {
    const compensation = metrics.findIndex((metric) => metric.key === 'compensation');
    expect(compensation).toBeGreaterThanOrEqual(0);
    const { container } = renderCard(compensation, true);
    const card = container.querySelector<HTMLElement>('.overview-card');
    expect(card!.dataset.featured).toBe('true');
    expect(card!.dataset.band).toBeTruthy();
    expect(container.querySelector('.overview-card-value')?.textContent).toBeTruthy();
  });
});

describe('overview card units', () => {
  it('names the unit of every metric next to the reading', () => {
    metrics.forEach((metric, index) => {
      const expected = dictionaries.ru[`overview.unit.${metric.key}`];
      expect(expected, metric.key).toBeTruthy();
      const { container, unmount } = renderCard(index);
      const unit = container.querySelector('.overview-card-unit');
      expect(unit, metric.key).not.toBeNull();
      expect(unit!.textContent, metric.key).toBe(expected);
      unmount();
    });
  });

  it('gives volume, money, share and count metrics distinct units', () => {
    const unitOf = (key: string) => dictionaries.ru[`overview.unit.${key}`];
    expect(unitOf('production')).toBe(unitOf('injection'));
    expect(unitOf('production')).not.toBe(unitOf('npv'));
    expect(unitOf('npv')).not.toBe(unitOf('activeWells'));
    expect(unitOf('watercut')).not.toBe(unitOf('activeWells'));
  });

  it('repeats the unit in the accessible plot title and the horizon footer', () => {
    const production = metrics.findIndex((metric) => metric.key === 'production');
    const { container } = renderCard(production);
    const unit = dictionaries.ru['overview.unit.production'];
    expect(container.querySelector('title')?.textContent).toContain(unit);
    expect(container.querySelector('.overview-card-span')?.textContent).toContain(unit);
  });
});
