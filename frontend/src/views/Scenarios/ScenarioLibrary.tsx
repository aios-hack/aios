import type { ScenarioEntry } from '../../api/types';
import { useDataset } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useScenario } from '../../state/ScenarioContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { formatNumber } from '../Timeline/format';

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
  const index = useDataset('scenarios');

  if (index.status === 'loading') {
    return <ViewStatus kind="loading" title={t('scenarios.library.loading')} />;
  }
  if (index.status === 'error') {
    return (
      <ViewStatus
        kind="error"
        title={t('scenarios.library.error')}
        hint={t('scenarios.library.errorHint')}
      />
    );
  }
  if (index.data.scenarios.length === 0) {
    return (
      <ViewStatus
        kind="empty"
        title={t('scenarios.library.empty')}
        hint={t('scenarios.library.emptyHint')}
      />
    );
  }

  return (
    <section className="scenarios-library">
      <h3 className="scenarios-heading">{t('scenarios.library.title')}</h3>
      <p className="scenarios-note">{t('scenarios.library.note')}</p>
      <ul className="scenarios-list">
        {index.data.scenarios.map((entry, position) => {
          const active =
            entry.id === activeId || (activeId === DEFAULT_SCENARIO_ID && position === 0);
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
