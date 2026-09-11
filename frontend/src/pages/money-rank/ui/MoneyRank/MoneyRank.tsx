import { useT } from '@/shared/i18n/I18nContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { usePlayback } from '@/entities/timeline/model/PlaybackContext';
import { MainChart } from '@/entities/timeline/ui/MainChart/MainChart';
import { NpvRank } from '@/pages/money-rank/ui/NpvRank';
import './MoneyRank.css';

export const MoneyRank = () => {
  const t = useT();
  const { timeline, stepIndex } = useTimeline();
  const { selectStep } = usePlayback();
  const stepCount = timeline.status === 'ready' ? timeline.data.steps.length : 0;
  const current = stepCount === 0 ? 0 : Math.min(stepIndex, stepCount - 1);

  return (
    <div className="money-rank" data-testid="money-workspace">
      <h2 className="money-rank-title">{t('npv.title')}</h2>
      {timeline.status === 'ready' && stepCount > 0 && (
        <MainChart steps={timeline.data.steps} stepIndex={current} onSelect={selectStep} />
      )}
      <NpvRank />
    </div>
  );
};
