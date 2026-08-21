import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { usePlayback } from '../../state/PlaybackContext';
import { MainChart } from '../Timeline/MainChart';
import { NpvRank } from '../NpvRank';

export const MoneyRank = () => {
  const t = useT();
  const { timeline, stepIndex } = useTimeline();
  const { selectStep } = usePlayback();
  const stepCount = timeline.status === 'ready' ? timeline.data.steps.length : 0;
  const current = stepCount === 0 ? 0 : Math.min(stepIndex, stepCount - 1);

  return (
    <div className="money-rank">
      <h2 className="money-rank-title">{t('npv.title')}</h2>
      {timeline.status === 'ready' && stepCount > 0 && (
        <MainChart steps={timeline.data.steps} stepIndex={current} onSelect={selectStep} />
      )}
      <NpvRank />
    </div>
  );
};
