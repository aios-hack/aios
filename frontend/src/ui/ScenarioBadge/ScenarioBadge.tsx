import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useOptionalScenario } from '../../state/ScenarioContext';
import './ScenarioBadge.css';

interface ScenarioBadgeProps {
  onOpenLibrary?: () => void;
}

export const ScenarioBadge = ({ onOpenLibrary }: ScenarioBadgeProps = {}) => {
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

  const kind = t(
    active.is_submitted ? 'scenarios.badge.submitted' : 'scenarios.badge.whatIf'
  );
  const label = t('scenarios.badge.open', { id: active.id, kind });

  if (!onOpenLibrary) {
    return (
      <p className="scenario-badge" data-guide="header-scenario" data-submitted={active.is_submitted} title={label}>
        <span className="scenario-badge-id">{active.id}</span>
      </p>
    );
  }

  return (
    <button
      type="button"
      className="scenario-badge"
      data-guide="header-scenario"
      data-submitted={active.is_submitted}
      title={label}
      aria-label={label}
      onClick={onOpenLibrary}
    >
      <span className="scenario-badge-id">{active.id}</span>
    </button>
  );
};
