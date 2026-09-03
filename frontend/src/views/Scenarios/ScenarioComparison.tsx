import { useState } from 'react';
import type { ScenarioEntry } from '../../api/types';
import { useScenarioDataset } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { SegmentedControl } from '../../ui/SegmentedControl';
import { ViewStatus } from '../../ui/ViewStatus';
import { formatNumber } from '../../ui/format';
import type { TaxMode } from '../NpvRank/types';
import { alternativesOf, compareScenarios, submittedOf, valueFor } from './comparison';
import './ScenariosCompare.css';

const MODES: TaxMode[] = ['preTax', 'withTax'];

interface ScenarioComparisonProps {
  entries: readonly ScenarioEntry[];
}

export const ScenarioComparison = ({ entries }: ScenarioComparisonProps) => {
  const { t, lang } = useI18n();
  const submitted = submittedOf(entries);
  const alternatives = alternativesOf(entries);
  const [otherId, setOtherId] = useState<string | null>(alternatives[0]?.id ?? null);
  const [mode, setMode] = useState<TaxMode>('preTax');

  const resolvedOtherId = otherId ?? alternatives[0]?.id ?? null;
  const baseNpv = useScenarioDataset('npv', submitted?.id ?? null);
  const otherNpv = useScenarioDataset('npv', resolvedOtherId);

  if (submitted === null || alternatives.length === 0 || resolvedOtherId === null) {
    return null;
  }
  if (baseNpv.status === 'error' || otherNpv.status === 'error') {
    return (
      <ViewStatus kind="error" title={t('scenarios.compare.error')} />
    );
  }
  if (baseNpv.status === 'loading' || otherNpv.status === 'loading') {
    return <ViewStatus kind="loading" title={t('scenarios.compare.loading')} />;
  }

  const result = compareScenarios(
    submitted.id,
    resolvedOtherId,
    baseNpv.data,
    otherNpv.data
  );
  const delta = valueFor(result.delta, mode);
  const better = delta > 0;
  const sign = better ? '+' : '';

  return (
    <section className="scenario-compare" data-guide="money-comparison-table">
      <header className="scenario-compare-head">
        <h3 className="scenarios-heading">{t('scenarios.compare.title')}</h3>
        <SegmentedControl
          options={MODES.map((value) => ({ value, label: t(`npv.mode.${value}`) }))}
          active={mode}
          label={t('npv.mode.legend')}
          onSelect={setMode}
        />
      </header>

      <div className="scenario-compare-body">
        <div className="scenario-compare-side">
          <span className="scenario-compare-label">{t('scenarios.compare.submitted')}</span>
          <span className="scenario-compare-id">{result.baseId}</span>
          <span className="scenario-compare-value">
            {formatNumber(lang, valueFor(result.base, mode))}
          </span>
          <span className="scenario-compare-basis">
            {t(`npv.mode.${mode}`)}, {t('scenarios.compare.unit')}
          </span>
        </div>

        <div className="scenario-compare-delta" data-better={better}>
          <span className="scenario-compare-delta-label">
            {t('scenarios.compare.delta')}
          </span>
          <span className="scenario-compare-delta-value">
            {sign}
            {formatNumber(lang, delta)}
          </span>
          <span className="scenario-compare-delta-unit">
            {t('scenarios.compare.unit')}
          </span>
        </div>

        <div className="scenario-compare-side scenario-compare-side--other">
          <span className="scenario-compare-label">{t('scenarios.compare.whatIf')}</span>
          {alternatives.length === 1 ? (
            <span className="scenario-compare-id">{alternatives[0].id}</span>
          ) : (
            <span className="scenario-compare-pick" data-guide="money-scenario-select">
              <SegmentedControl
                options={alternatives.map((entry) => ({
                  value: entry.id,
                  label: entry.id
                }))}
                active={resolvedOtherId}
                label={t('scenarios.compare.pick')}
                onSelect={setOtherId}
              />
            </span>
          )}
          <span className="scenario-compare-value">
            {formatNumber(lang, valueFor(result.other, mode))}
          </span>
          <span className="scenario-compare-basis">
            {t(`npv.mode.${mode}`)}, {t('scenarios.compare.unit')}
          </span>
        </div>
      </div>

      <p className="scenario-compare-caveat">{t('scenarios.compare.caveat')}</p>
    </section>
  );
};
