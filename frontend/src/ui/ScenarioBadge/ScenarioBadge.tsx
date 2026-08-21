import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useOptionalScenario } from '../../state/ScenarioContext';
import { InfoHint } from '../InfoHint';
import './ScenarioBadge.css';

interface ScenarioBadgeProps {
  onOpenDetails?: (scenarioId: string) => void;
}

export const ScenarioBadge = ({ onOpenDetails }: ScenarioBadgeProps = {}) => {
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
      {onOpenDetails ? (
        <button
          type="button"
          className="scenario-badge-details"
          onClick={() => onOpenDetails(active.id)}
        >
          <span className="scenario-badge-id">{active.id}</span>
          <span className="scenario-badge-kind">
            {t(active.is_submitted ? 'scenarios.badge.submitted' : 'scenarios.badge.whatIf')}
          </span>
        </button>
      ) : (
        <>
          <span className="scenario-badge-id">{active.id}</span>
          <span className="scenario-badge-kind">
            {t(active.is_submitted ? 'scenarios.badge.submitted' : 'scenarios.badge.whatIf')}
          </span>
        </>
      )}
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
