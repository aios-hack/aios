import { useCallback } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { useExplainAction } from './useExplainAction';
import './ExplainButton.css';

interface ExplainButtonProps {
  well: string;
  step?: number;
  compact?: boolean;
}

export const ExplainButton = ({ well, step, compact = false }: ExplainButtonProps) => {
  const { t } = useI18n();
  const { stepIndex } = useTimeline();
  const explain = useExplainAction();
  const target = step ?? stepIndex;
  const onClick = useCallback(
    (event: { stopPropagation: () => void }) => {
      event.stopPropagation();
      explain?.({ well, step: target });
    },
    [explain, well, target]
  );

  if (explain === null) {
    return null;
  }

  return (
    <button
      type="button"
      className="jarvis-explain"
      data-compact={compact}
      data-testid={`jarvis-explain-${well}`}
      title={t('jarvis.explainHint')}
      aria-label={t('jarvis.explainQuestion', { well })}
      onClick={onClick}
    >
      {t('jarvis.explain')}
    </button>
  );
};
