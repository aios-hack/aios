import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactNode } from 'react';
import type { FieldNormBand, TimelineStep } from '@/entities/timeline/types';
import { I18nProvider } from '@/shared/i18n/I18nContext';
import { CompensationPanel } from '@/pages/history-table/ui/CompensationPanel/CompensationPanel';

const DIAGNOSTIC_BAND: FieldNormBand = {
  min: 0.85,
  max: 1.15,
  source: 'diagnostic',
  enforcement: 'diagnostic',
  scope: 'field_and_groups',
  basis: 'surface'
};

const step = (field: Partial<TimelineStep['field']> = {}): TimelineStep => ({
  control_step: 0,
  date: '2007-01-01',
  terminal: false,
  field: {
    production: 1000,
    injection: 950,
    compensation: 0.95,
    compensation_surface: 0.95,
    compensation_reservoir: null,
    compensation_defined: true,
    npv_cumulative: 100,
    active_wells: 4,
    ...field
  },
  wells: []
});

const renderPanel = (
  current: TimelineStep | undefined,
  band: FieldNormBand | null = DIAGNOSTIC_BAND
): HTMLElement => {
  const withProviders = (node: ReactNode) => <I18nProvider>{node}</I18nProvider>;
  const { container } = render(
    withProviders(<CompensationPanel step={current} band={band} />)
  );
  return container;
};

const textOf = (container: HTMLElement, testId: string): string =>
  container.querySelector(`[data-testid="${testId}"]`)?.textContent ?? '';

describe('compensation panel on the timeline', () => {
  it('shows the compensation of the current step', () => {
    const container = renderPanel(step());
    expect(textOf(container, 'compensation-surface')).toContain('0,95');
  });

  it('labels the corridor with its source so it is not read as a requirement', () => {
    const container = renderPanel(step());
    const source = container.querySelector('[data-testid="compensation-source"]');
    expect(source).not.toBeNull();
    expect(source?.getAttribute('data-source')).toBe('diagnostic');
    expect(source?.textContent).toContain('диагностический');
    expect(source?.textContent).toContain('не требование организаторов');
  });

  it('prints the diagnostic corridor bounds, not the organiser band', () => {
    const container = renderPanel(step());
    const corridor = textOf(container, 'compensation-corridor');
    expect(corridor).toContain('0,85');
    expect(corridor).toContain('1,15');
    expect(corridor).not.toContain('1,46');
  });

  it('shows both readings when the reservoir value is available', () => {
    const container = renderPanel(step({ compensation_reservoir: 0.81 }));
    expect(textOf(container, 'compensation-surface')).toContain('0,95');
    expect(textOf(container, 'compensation-reservoir')).toContain('0,81');
    expect(container.querySelector('[data-testid="compensation-surface-note"]')).toBeNull();
  });

  it('says the reservoir reading is not recorded instead of inventing one', () => {
    const container = renderPanel(step({ compensation_reservoir: null }));
    expect(textOf(container, 'compensation-reservoir')).toContain('не записано');
    expect(textOf(container, 'compensation-reservoir')).not.toContain('0,00');
  });

  it('says plainly that only the surface figure is shown', () => {
    const container = renderPanel(step({ compensation_reservoir: null }));
    expect(textOf(container, 'compensation-surface-note')).toContain('поверхностная');
  });

  it('marks a value outside the corridor', () => {
    const container = renderPanel(
      step({ compensation: 0.4, compensation_surface: 0.4 })
    );
    const reading = container.querySelector('[data-testid="compensation-surface"]');
    expect(reading?.getAttribute('data-status')).toBe('outside');
  });

  it('marks a value inside the corridor', () => {
    const reading = renderPanel(step()).querySelector(
      '[data-testid="compensation-surface"]'
    );
    expect(reading?.getAttribute('data-status')).toBe('inside');
  });

  it('calls a zero-withdrawal step undefined, not zero', () => {
    const container = renderPanel(
      step({
        production: 0,
        compensation: null,
        compensation_surface: null,
        compensation_defined: false
      })
    );
    expect(textOf(container, 'compensation-surface')).toContain('не записано');
    expect(textOf(container, 'compensation-undefined')).toContain('не определена');
  });

  it('says the diagnostic mode does not block the plan', () => {
    const container = renderPanel(step());
    expect(textOf(container, 'compensation-enforcement')).toContain('не блокирует');
  });

  it('hides the non-blocking note when enforcement is hard', () => {
    const container = renderPanel(step(), { ...DIAGNOSTIC_BAND, enforcement: 'hard' });
    expect(container.querySelector('[data-testid="compensation-enforcement"]')).toBeNull();
  });

  it('names the control scope', () => {
    const container = renderPanel(step());
    expect(textOf(container, 'compensation-scope')).toContain('по месторождению и по группам');
  });

  it('names a field-only scope', () => {
    const container = renderPanel(step(), { ...DIAGNOSTIC_BAND, scope: 'field' });
    expect(textOf(container, 'compensation-scope')).toContain('по месторождению');
  });

  it('reports "not recorded" when there is no step at all', () => {
    const container = renderPanel(undefined);
    expect(container.textContent).toContain('не записано');
  });

  it('omits the corridor entirely when the artifact carries no band', () => {
    const container = renderPanel(step(), null);
    expect(container.querySelector('[data-testid="compensation-corridor"]')).toBeNull();
    expect(textOf(container, 'compensation-surface')).toContain('0,95');
  });

  it('falls back to the plain compensation field when no surface field exists', () => {
    const legacy = step();
    delete legacy.field.compensation_surface;
    expect(textOf(renderPanel(legacy), 'compensation-surface')).toContain('0,95');
  });
});
