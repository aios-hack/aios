import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ConstraintsEditor } from './ConstraintsEditor';
import { ScenarioLibrary } from './ScenarioLibrary';
import './ScenariosLibrary.css';

const FALLBACK_INTERVALS = 224;

export const Scenarios = () => {
  const t = useT();
  const { timeline } = useTimeline();
  const nIntervals =
    timeline.status === 'ready' ? timeline.data.n_intervals : FALLBACK_INTERVALS;

  return (
    <div className="scenarios">
      <p className="scenarios-lead">{t('scenarios.lead')}</p>
      <ScenarioLibrary />
      <ConstraintsEditor nIntervals={nIntervals} />
    </div>
  );
};
