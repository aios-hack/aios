import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useOptionalScenario } from '../../state/ScenarioContext';
import { InfoHint } from '../InfoHint';
import './ScenarioBadge.css';

export const ScenarioBadge = () => {
  const t = useT();
  const { activeId } = useOptionalScenario();
  const index = useDataset('scenarios');

  if (index.status !== 'ready' || index.data.scenarios.length < 2) {
    return null;
  }

  const entries = index.data.scenarios;
  const active =
    entries.find((entry) => entry.id === activeId) ??
    (activeId === DEFAULT_SCENARIO_ID ? entries[0] : null);

  if (!active) {
    return null;
  }

  return (
    <p className="scenario-badge-bar" data-submitted={active.is_submitted}>
      <span className="scenario-badge-label">{t('scenarios.badge.viewing')}</span>
      <span className="scenario-badge-id">{active.id}</span>
      <span className="scenario-badge-kind">
        {t(active.is_submitted ? 'scenarios.badge.submitted' : 'scenarios.badge.whatIf')}
      </span>
      <InfoHint
        label={t('scenarios.badge.hintLabel')}
        text={t(
          active.is_submitted
            ? 'scenarios.badge.submittedHint'
            : 'scenarios.badge.whatIfHint'
        )}
      />
    </p>
  );
};
