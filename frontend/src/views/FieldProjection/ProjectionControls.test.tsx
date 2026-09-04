import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { edgesHintText, ProjectionControls, type EdgesMeta } from './ProjectionControls';

const { ru } = dictionaries;

const t = (key: string, params?: Record<string, string | number>): string => {
  const template = ru[key] ?? key;
  if (!params) {
    return template;
  }
  return Object.entries(params).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
    template
  );
};

const measuredMeta: EdgesMeta = {
  kind: 'graph',
  provenance: 'model-z-base-run',
  lag_months: 2,
  amplitude: 1.11,
  stability: 0.5327067980424265,
  rank: 41,
  condition_number: 7.925869476656569,
  lambda_measured: true
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ThemeProvider>{node}</ThemeProvider>
  </I18nProvider>
);

const renderControls = (edgesMeta: EdgesMeta) =>
  render(
    withProviders(
      <ProjectionControls
        pole="graph"
        threshold={0.3}
        thresholdMin={0.1}
        thresholdMax={0.9}
        shownEdges={12}
        totalEdges={40}
        layers={[{ id: 1, k_min: 1, k_max: 3 }]}
        layerFilter="all"
        edgesMeta={edgesMeta}
        onPole={() => undefined}
        onThreshold={() => undefined}
        onLayerFilter={() => undefined}
        legendNotes={[]}
      />
    )
  );

const openHint = () => {
  fireEvent.click(screen.getByRole('button', { name: ru['projection.edges.hint.label'] }));
  return screen.getByRole('tooltip').textContent ?? '';
};

describe('edgesHintText', () => {
  it('states that connectivity is measured by a design of experiments, not by distance', () => {
    const text = edgesHintText(measuredMeta, t, 'ru');

    expect(text).toContain('планом эксперимента');
    expect(text).toContain('возмущ');
    expect(text).toContain('не расстояние между скважинами');
  });

  it('takes lag, stability, rank and condition number from the data', () => {
    const text = edgesHintText(measuredMeta, t, 'ru');

    expect(text).toContain('2 мес.');
    expect(text).toContain('0,53');
    expect(text).toContain('41');
    expect(text).toContain('7,9');
    expect(text).not.toContain('{');
  });

  it('spells a zero lag out instead of printing a bare zero', () => {
    const text = edgesHintText({ ...measuredMeta, lag_months: 0 }, t, 'ru');

    expect(text).toContain(ru['projection.edges.lagZero']);
  });

  it('says connectivity is not measured when meta is missing', () => {
    expect(edgesHintText(undefined, t, 'ru')).toBe(ru['projection.edges.hint.unmeasured']);
  });

  it('says connectivity is not measured when lambda_measured is not true', () => {
    const meta: EdgesMeta = { ...measuredMeta, lambda_measured: undefined };

    expect(edgesHintText(meta, t, 'ru')).toBe(ru['projection.edges.hint.unmeasured']);
  });

  it('never shows empty numbers when a metric is absent', () => {
    const meta = { ...measuredMeta, stability: Number.NaN };
    const text = edgesHintText(meta, t, 'ru');

    expect(text).toBe(ru['projection.edges.hint.unmeasured']);
    expect(text).not.toContain('NaN');
    expect(text).not.toContain('—');
  });

  it('translates the hint into English as well', () => {
    const en = (key: string, params?: Record<string, string | number>): string => {
      const template = dictionaries.en[key] ?? key;
      if (!params) {
        return template;
      }
      return Object.entries(params).reduce(
        (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
        template
      );
    };
    const text = edgesHintText(measuredMeta, en, 'en');

    expect(text).toContain('design of experiments');
    expect(text).toContain('41');
    expect(text).not.toContain('{');
  });
});

describe('ProjectionControls edges hint', () => {
  it('renders the hint trigger next to the graph controls', () => {
    const { container } = renderControls(measuredMeta);

    expect(container.querySelector('[data-testid="projection-edges-hint"]')).not.toBeNull();
    expect(
      screen.getByRole('button', { name: ru['projection.edges.hint.label'] })
    ).not.toBeNull();
  });

  it('shows the measured numbers when the hint is opened', () => {
    renderControls(measuredMeta);

    const text = openHint();

    expect(text).toContain('планом эксперимента');
    expect(text).toContain('41');
    expect(text).toContain('0,53');
  });

  it('admits that connectivity is not measured when the artifact has no meta', () => {
    renderControls(undefined);

    expect(openHint()).toBe(ru['projection.edges.hint.unmeasured']);
  });
});
