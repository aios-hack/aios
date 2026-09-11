import { SparkleIcon } from '@phosphor-icons/react';
import { useCallback } from 'react';
import { useT } from '@/shared/i18n/I18nContext';
import { useAskJarvis } from '@/features/ask-jarvis/ui/useAskJarvis';
import './AskJarvis.css';

interface AskJarvisProps {
  question: string;
  label?: string;
  compact?: boolean;
  testId?: string;
}

export const AskJarvis = ({ question, label, compact = false, testId }: AskJarvisProps) => {
  const t = useT();
  const ask = useAskJarvis();

  const onClick = useCallback(
    (event: { stopPropagation: () => void }) => {
      event.stopPropagation();
      ask?.(question);
    },
    [ask, question]
  );

  if (ask === null) {
    return null;
  }

  return (
    <button
      type="button"
      className="ask-jarvis"
      data-compact={compact}
      data-testid={testId ?? 'ask-jarvis'}
      title={question}
      aria-label={question}
      onClick={onClick}
    >
      <SparkleIcon size={12} weight="bold" aria-hidden="true" />
      {label ?? t('askJarvis.label')}
    </button>
  );
};
