import { DASH, formatNumber } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readCouncil } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './CouncilCard.css';

export const CouncilCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const council = readCouncil(payload);
  if (council === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-council">
      <p className="jarvis-council-when">
        {t('jarvis.contextStep')} {council.step}
        {council.date === null ? '' : ` · ${council.date}`}
        {council.group === null ? '' : ` · ${council.group}`}
      </p>
      <ol className="jarvis-council-levels">
        {council.levels.map((level) => (
          <li className="jarvis-council-level" key={`${level.rank}-${level.agent}`}>
            <span className="jarvis-council-rank">R{level.rank}</span>
            <span className="jarvis-council-agent">{level.agent}</span>
            <span className="jarvis-council-verdict" data-verdict={level.verdict}>
              {level.verdict.length === 0 ? DASH : level.verdict}
            </span>
            <span className="jarvis-council-bounds">
              {level.bounds.length === 0
                ? DASH
                : level.bounds.map((bound) => formatNumber(lang, bound, 1)).join(' → ')}
            </span>
            <span className="jarvis-council-decisions">
              {t('jarvis.councilDecisions', { count: String(level.decisions) })}
            </span>
          </li>
        ))}
      </ol>
      {council.outcome.well === null && council.outcome.action === null ? null : (
        <p className="jarvis-council-outcome">
          <span className="jarvis-council-outcome-label">{t('jarvis.councilOutcome')}</span>
          {council.outcome.well ?? DASH} · {council.outcome.action ?? DASH}
          {council.outcome.rule === null ? '' : ` · ${council.outcome.rule}`}
        </p>
      )}
      {council.agents_fired.length === 0 ? null : (
        <p className="jarvis-council-agents">{council.agents_fired.join(' · ')}</p>
      )}
    </div>
  );
};
