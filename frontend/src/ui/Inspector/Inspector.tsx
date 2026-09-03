import { XIcon } from '@phosphor-icons/react';
import { useId, type ReactNode } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { useCloseBehaviour } from './useCloseBehaviour';
import type { InspectorContext } from './InspectorContext';
import './Inspector.css';

interface InspectorProps<T extends InspectorContext> {
  context: T | null;
  title: string;
  onClose: () => void;
  closing: boolean;
  children: ReactNode;
}

export const Inspector = <T extends InspectorContext>({
  context,
  title,
  onClose,
  closing,
  children
}: InspectorProps<T>) => {
  const { t } = useI18n();
  const titleId = useId();
  const open = context !== null;

  useCloseBehaviour(open, onClose);

  if (context === null) {
    return null;
  }

  return (
    <aside
      className="inspector"
      data-closing={closing}
      data-testid="inspector"
      data-guide="inspector-panel"
      aria-labelledby={titleId}
    >
      <header className="inspector-header">
        <h3 className="inspector-title" id={titleId}>
          {title}
        </h3>
        <button
          type="button"
          className="inspector-close"
          data-guide="inspector-close"
          aria-label={t('inspector.close')}
          onClick={onClose}
        >
          <XIcon size={16} weight="bold" aria-hidden="true" />
        </button>
      </header>
      <div className="inspector-body">{children}</div>
    </aside>
  );
};
