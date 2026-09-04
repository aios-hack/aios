import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import type { ScenarioEntry } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { MoneyProvenance } from './MoneyProvenance';

const { ru } = dictionaries;

const emptyConstraints: ScenarioEntry['constraints'] = {
  injection_limits: 0,
  liquid_limits: 0,
  production_floors: 0,
  watercut_limits: 0,
  well_outages: 0,
  infrastructure: 0,
  years: [],
  outage_wells: [],
  empty: true
};

const scenario = (patch: Partial<ScenarioEntry>): ScenarioEntry => ({
  id: 'case',
  config_hash: 'hash',
  converged: true,
  self_consistent: true,
  is_submitted: false,
  npv_methodology: null,
  constraints: emptyConstraints,
  ...patch
});

const ENTRIES: ScenarioEntry[] = [
  scenario({
    id: 'base',
    is_submitted: true,
    npv_methodology: 11873122324.910866,
    final_npv: { npv_rub: 11873122324.910866, run_id: '20260816T200926-8b4da543d1ed' },
    run_validation_clean: true
  }),
  scenario({
    id: 'candidate',
    predicted_npv_rub: 10558445546.343525,
    ood_score: 2.0197874298096283,
    ood_threshold: 0
  }),
  scenario({ id: 'whatif-injection-cut' })
];

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ThemeProvider>{node}</ThemeProvider>
  </I18nProvider>
);

const row = (id: string): HTMLElement => screen.getByTestId(`money-provenance-${id}`);

describe('MoneyProvenance', () => {
  it('shows a run id for a number confirmed by a simulator run', () => {
    render(withProviders(<MoneyProvenance entries={ENTRIES} />));

    const item = row('base');
    expect(item.getAttribute('data-kind')).toBe('run');
    expect(item.textContent).toContain('20260816T200926-8b4da543d1ed');
    expect(item.textContent).toContain('Подтверждено прогоном');
  });

  it('calls a model number a forecast and never a confirmed fact', () => {
    render(withProviders(<MoneyProvenance entries={ENTRIES} />));

    const item = row('candidate');
    expect(item.getAttribute('data-kind')).toBe('forecast');
    expect(item.textContent).toContain(ru['npv.provenance.forecast']);
    expect(item.textContent).not.toContain('Подтверждено прогоном');
  });

  it('says that nothing is measured instead of showing a number', () => {
    render(withProviders(<MoneyProvenance entries={ENTRIES} />));

    const item = row('whatif-injection-cut');
    expect(item.getAttribute('data-kind')).toBe('unmeasured');
    expect(item.textContent).toContain(ru['npv.provenance.unmeasured']);
    expect(item.textContent).toContain('—');
  });

  it('adds a synthetic warning when the artifact is demonstration data', () => {
    render(
      withProviders(
        <MoneyProvenance
          entries={ENTRIES}
          meta={{ kind: 'scenarios', provenance: 'synthetic-demo' }}
        />
      )
    );

    expect(screen.getByTestId('npv-synthetic-base').textContent).toBe(
      ru['npv.provenance.synthetic']
    );
  });

  it('keeps quiet when there are no scenarios at all', () => {
    const { container } = render(withProviders(<MoneyProvenance entries={[]} />));

    expect(container.querySelector('.money-provenance')).toBeNull();
  });

  it('leaves no untranslated placeholder in the rendered text', () => {
    const { container } = render(withProviders(<MoneyProvenance entries={ENTRIES} />));

    expect(container.textContent).not.toContain('{');
    expect(container.textContent).not.toContain('npv.provenance.');
  });
});
