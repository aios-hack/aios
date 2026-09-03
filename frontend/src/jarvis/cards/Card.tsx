import type { ReactNode } from 'react';
import { useT } from '../../i18n/I18nContext';
import type { JarvisCard } from '../transport/events';
import { provenanceKindOf, provenanceTitleKey } from './provenance';
import './Card.css';

interface CardProps {
  card: JarvisCard;
  expanded: boolean;
  onToggle: () => void;
  onOpenInConsole: () => void;
  children: ReactNode;
}

export const Card = ({ card, expanded, onToggle, onOpenInConsole, children }: CardProps) => {
  const t = useT();
  const kind = provenanceKindOf(card.provenance);

  return (
    <article
      className="jarvis-card"
      role="group"
      aria-label={t('jarvis.cardLabel', { title: card.title })}
      data-type={card.type}
      data-expanded={expanded ? 'true' : undefined}
    >
      <header className="jarvis-card-head">
        <h3 className="jarvis-card-title">{card.title}</h3>
        <span className="jarvis-card-chip" data-kind={kind} title={t(provenanceTitleKey(kind))}>
          {card.provenance}
        </span>
      </header>
      <div className="jarvis-card-body">{children}</div>
      <footer className="jarvis-card-foot">
        <button type="button" className="jarvis-card-toggle" onClick={onToggle}>
          {expanded ? t('jarvis.collapse') : t('jarvis.expand')}
        </button>
        {card.action === undefined ? null : (
          <button type="button" className="jarvis-card-open" onClick={onOpenInConsole}>
            {t('jarvis.openInConsole')}
          </button>
        )}
      </footer>
    </article>
  );
};
