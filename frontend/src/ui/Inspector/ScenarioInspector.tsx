import type { ScenarioEntry } from '../../api/types';
import { useDataset } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useScenario } from '../../state/ScenarioContext';
import { formatNumber } from '../../ui/format';
import { ViewStatus } from '../../ui/ViewStatus';
import './ScenarioInspector.css';

interface ScenarioInspectorProps {
  scenarioId: string;
}

const findEntry = (entries: ScenarioEntry[], scenarioId: string): ScenarioEntry | null =>
  entries.find((entry) => entry.id === scenarioId) ??
  (scenarioId === DEFAULT_SCENARIO_ID ? (entries[0] ?? null) : null);

export const ScenarioInspector = ({ scenarioId }: ScenarioInspectorProps) => {
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

  const entry = findEntry(index.data.scenarios, scenarioId);
  if (entry === null) {
    return <ViewStatus kind="empty" title={t('scenarios.library.empty')} />;
  }

  const active = entry.id === activeId || (activeId === DEFAULT_SCENARIO_ID && entry.id === '');
  const validated = entry.run_validation_clean;

  return (
    <div className="scenario-inspector" data-testid="scenario-inspector">
      <p className="scenario-inspector-status">
        <span
          className="scenario-inspector-badge"
          data-kind={entry.is_submitted ? 'submitted' : 'whatif'}
        >
          {t(entry.is_submitted ? 'scenarios.badge.submitted' : 'scenarios.badge.whatIf')}
        </span>
        {!entry.converged && (
          <span className="scenario-inspector-flag" data-ok="false">
            {t('scenarios.flag.notConverged')}
          </span>
        )}
        {!entry.self_consistent && (
          <span className="scenario-inspector-flag" data-ok="false">
            {t('scenarios.flag.notSelfConsistent')}
          </span>
        )}
      </p>
      <dl className="scenario-inspector-fields">
        {entry.final_npv && (
          <div className="scenario-inspector-field">
            <dt>{t('inspector.scenario.runId')}</dt>
            <dd>{entry.final_npv.run_id}</dd>
          </div>
        )}
        {validated !== undefined && validated !== null && (
          <div className="scenario-inspector-field">
            <dt>{t('inspector.scenario.validation')}</dt>
            <dd data-ok={validated}>
              {t(validated ? 'inspector.scenario.validationClean' : 'inspector.scenario.validationDirty')}
            </dd>
          </div>
        )}
        {entry.npv_methodology !== null && (
          <div className="scenario-inspector-field">
            <dt>{t('scenarios.library.npvLabel')}</dt>
            <dd>{formatNumber(lang, entry.npv_methodology)}</dd>
          </div>
        )}
      </dl>
      <button
        type="button"
        className="scenario-inspector-activate"
        data-active={active}
        disabled={active}
        onClick={() => selectScenario(entry.id)}
      >
        {t(active ? 'scenarios.library.active' : 'scenarios.library.switch')}
      </button>
    </div>
  );
};
