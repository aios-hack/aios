import type { ArtifactMeta, ScenarioEntry } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber } from '../../ui/format';
import { NpvProvenanceTag } from './NpvProvenanceTag';
import { npvProvenanceOf, type ArtifactProvenance } from './provenance';
import './MoneyProvenance.css';

interface MoneyProvenanceProps {
  entries: readonly ScenarioEntry[];
  meta?: ArtifactMeta;
}

const measured = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const shownValueOf = (scenario: ScenarioEntry): number | null => {
  const final = scenario.final_npv;
  if (final && measured(final.npv_rub)) {
    return final.npv_rub;
  }
  if (measured(scenario.predicted_npv_rub)) {
    return scenario.predicted_npv_rub;
  }
  if (measured(scenario.npv_methodology)) {
    return scenario.npv_methodology;
  }
  return null;
};

export const MoneyProvenance = ({ entries, meta }: MoneyProvenanceProps) => {
  const { t, lang } = useI18n();

  if (entries.length === 0) {
    return null;
  }

  const artifact: ArtifactProvenance = meta;

  return (
    <section className="money-provenance" data-guide="money-provenance">
      <h3 className="money-provenance-title">{t('npv.provenance.title')}</h3>
      <ul className="money-provenance-list">
        {entries.map((entry) => {
          const value = shownValueOf(entry);
          const provenance = npvProvenanceOf(entry, artifact);
          return (
            <li
              className="money-provenance-item"
              key={entry.id}
              data-kind={provenance.kind}
              data-testid={`money-provenance-${entry.id}`}
            >
              <span className="money-provenance-id">{entry.id}</span>
              <span className="money-provenance-value">
                {value === null ? DASH : formatNumber(lang, value)}
              </span>
              <span className="money-provenance-unit">{t('scenarios.compare.unit')}</span>
              <NpvProvenanceTag provenance={provenance} scenarioId={entry.id} />
            </li>
          );
        })}
      </ul>
    </section>
  );
};
