import type { ScenarioEntry, ScenariosFile } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { useScenario } from '../../state/ScenarioContext';
import { useJsonResource } from '../../state/TimelineContext';
import { formatNumber } from '../Timeline/format';

const isScenariosFile = (data: unknown): data is ScenariosFile =>
  typeof data === 'object' &&
  data !== null &&
  Array.isArray((data as { scenarios?: unknown }).scenarios);

const summaryOf = (entry: ScenarioEntry): number =>
  entry.constraints.injection_limits +
  entry.constraints.liquid_limits +
  entry.constraints.production_floors +
  entry.constraints.watercut_limits +
  entry.constraints.well_outages +
  entry.constraints.infrastructure;

export const ScenarioLibrary = () => {
  const { t, lang } = useI18n();
  const { activeId, selectScenario } = useScenario();
  const index = useJsonResource('/data/scenarios.json', isScenariosFile);

  if (index.status === 'loading') {
    return <p className="scenarios-status">{t('scenarios.library.loading')}</p>;
  }
  if (index.status === 'error') {
    return (
      <p className="scenarios-status scenarios-status-error" role="alert">
        {t('scenarios.library.error')}
      </p>
    );
  }
  if (index.data.scenarios.length === 0) {
    return <p className="scenarios-status">{t('scenarios.library.empty')}</p>;
  }

  return (
    <section className="scenarios-library">
      <h3 className="scenarios-heading">{t('scenarios.library.title')}</h3>
      <p className="scenarios-note">{t('scenarios.library.note')}</p>
      <ul className="scenarios-list">
        {index.data.scenarios.map((entry) => {
          const active = entry.id === activeId;
          return (
            <li key={entry.id}>
              <button
                type="button"
                className="scenarios-item"
                data-scenario-id={entry.id}
                data-submitted={entry.is_submitted}
                data-active={active}
                aria-pressed={active}
                onClick={() => selectScenario(entry.id)}
              >
                <span className="scenarios-item-head">
                  <span className="scenarios-item-id">{entry.id}</span>
                  <span
                    className="scenarios-badge"
                    data-kind={entry.is_submitted ? 'submitted' : 'whatif'}
                  >
                    {t(entry.is_submitted ? 'scenarios.badge.submitted' : 'scenarios.badge.whatIf')}
                  </span>
                </span>
                <span className="scenarios-item-flags">
                  <span className="scenarios-flag" data-ok={entry.converged}>
                    {t(entry.converged ? 'scenarios.flag.converged' : 'scenarios.flag.notConverged')}
                  </span>
                  <span className="scenarios-flag" data-ok={entry.self_consistent}>
                    {t(
                      entry.self_consistent
                        ? 'scenarios.flag.selfConsistent'
                        : 'scenarios.flag.notSelfConsistent'
                    )}
                  </span>
                </span>
                {entry.npv_methodology !== null && (
                  <span className="scenarios-item-npv">
                    {t('scenarios.library.npv', {
                      value: formatNumber(lang, entry.npv_methodology)
                    })}
                  </span>
                )}
                <span className="scenarios-item-summary">
                  {entry.constraints.empty
                    ? t('scenarios.library.noConstraints')
                    : t('scenarios.library.constraintsCount', { count: summaryOf(entry) })}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
};
